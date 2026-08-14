"""Lectures SQL du miroir pour le pilotage financier — aucun calcul métier ici.

Même arbitrage que `uc_commercial/queries.py` : ces requêtes attaquent directement
les tables du miroir via `AsyncSessionLocal` plutôt que d'élargir le port
`CRMRepository`, qui est une ABC partagée par cinq profils. Les lectures déjà
couvertes par le port (exposition aux impayés, statistiques de marge, top
fournisseurs) sont réutilisées telles quelles côté router et NON réécrites ici.

Deux précisions qui expliquent la forme des requêtes :

- le nom du client ne vit pas dans `invoices` : la table ne porte que `client_id`.
  La jointure sur `clients` est donc systématique, et 92 factures sur 2 957 ne
  trouvent pas leur client (fiche supprimée ou hors périmètre `customer_rank`).
  Elles ne sont jamais écartées — un encours sans nom reste un encours ; elles
  portent un libellé explicite et sont comptées comme défaut de qualité ;
- les montants sont pris tels quels (devise société, cf. le docstring du module) ;
  la devise du document est remontée pour permettre le contrôle de qualité, jamais
  pour convertir quoi que ce soit ici.
"""
from __future__ import annotations

from sqlalchemy import text

from db.database import AsyncSessionLocal

# États de commande retenus pour le CA — mêmes états que le reste du cockpit.
_ETATS_CA = "state IN ('sale', 'done')"

# Statut de facture écarté des encours : une facture annulée n'est ni une créance,
# ni un encaissement à venir. Elle reste comptée dans les totaux de qualité.
_STATUT_ANNULE = "cancelled"


async def _rows(sql: str, params: dict | None = None) -> list:
    async with AsyncSessionLocal() as session:
        return (await session.execute(text(sql), params or {})).fetchall()


async def _scalaire(sql: str, params: dict | None = None) -> int:
    rows = await _rows(sql, params)
    return int(rows[0][0] or 0) if rows else 0


# ── Factures clients (créances) ──────────────────────────────────────────────

async def fetch_factures_clients() -> list[dict]:
    """Toutes les factures clients, avec le nom du client et la date de règlement.

    Une seule lecture sert quatre écrans (DSO, balance âgée, mauvais payeurs,
    échéancier d'encaissement) : les séparer ferait quatre fois la même jointure
    sur 2 957 lignes.
    """
    rows = await _rows("""
        SELECT i.invoice_id, i.invoice_name, i.client_id,
               COALESCE(NULLIF(TRIM(c.name), ''), '') AS client,
               i.amount, i.amount_residual, i.currency,
               i.invoice_date, i.due_date, i.status, i.payment_date
        FROM invoices i
        LEFT JOIN clients c ON c.client_id = i.client_id
    """)
    return [
        {
            "invoice_id": r[0],
            "reference": r[1] or f"facture {r[0]}",
            "client_id": r[2],
            # Le client inconnu est nommé pour ce qu'il est : un encours orphelin
            # affiché « (client inconnu) » se conteste et se corrige, un encours
            # masqué ne se voit jamais.
            "client": r[3] or "(client hors référentiel)",
            "client_connu": bool(r[3]),
            "montant_xof": round(r[4] or 0),
            "reste_du_xof": round(r[5] or 0),
            "devise": r[6] or "XOF",
            "date_facture": str(r[7])[:10] if r[7] else None,
            "echeance": str(r[8])[:10] if r[8] else None,
            "statut": r[9] or "",
            "date_reglement": str(r[10])[:10] if r[10] else None,
            "annulee": (r[9] or "") == _STATUT_ANNULE,
        }
        for r in rows
    ]


# ── Achats fournisseurs (charges engagées) ───────────────────────────────────

async def fetch_achats() -> list[dict]:
    """Commandes d'achat confirmées — la seule mesure de charge disponible.

    `dossier_id` est remonté bien qu'il ne soit renseigné que sur 4 commandes sur
    2 133 : c'est précisément ce que le contrôle de qualité doit pouvoir compter.
    """
    rows = await _rows("""
        SELECT order_id, name, client_name, client_id, amount, currency,
               date_order, state, dossier_id
        FROM purchase_orders
    """)
    return [
        {
            "order_id": r[0],
            "reference": r[1] or f"achat {r[0]}",
            "fournisseur": (r[2] or "").strip() or "(fournisseur sans nom)",
            "fournisseur_id": r[3],
            "montant_xof": round(r[4] or 0),
            "devise": r[5] or "XOF",
            "date": str(r[6])[:10] if r[6] else None,
            "etat": r[7] or "",
            "dossier": (r[8] or "").strip() or None,
        }
        for r in rows
    ]


# ── Dettes fournisseurs (vides à ce jour, cf. statique.RAISON_DPO_STATIQUE) ──

async def fetch_factures_fournisseurs() -> list[dict]:
    """Factures fournisseurs — table VIDE aujourd'hui, lue quand même.

    C'est volontaire : le module calcule un DPO réel dès que la synchronisation
    des `in_invoice` sera en place, sans changer de code ni de forme de réponse.
    Câbler le gabarit en dur aurait rendu ce basculement invisible.
    """
    rows = await _rows("""
        SELECT invoice_id, supplier_id, supplier_name, amount, amount_residual,
               currency, invoice_date, due_date, payment_state, payment_date
        FROM supplier_invoices
    """)
    return [
        {
            "invoice_id": r[0],
            "fournisseur_id": r[1],
            "fournisseur": (r[2] or "").strip() or "(fournisseur sans nom)",
            "montant_xof": round(r[3] or 0),
            "reste_du_xof": round(r[4] or 0),
            "devise": r[5] or "XOF",
            "date_facture": str(r[6])[:10] if r[6] else None,
            "echeance": str(r[7])[:10] if r[7] else None,
            "statut_paiement": r[8] or "",
            "date_reglement": str(r[9])[:10] if r[9] else None,
        }
        for r in rows
    ]


async def fetch_delais_negocies() -> list[dict]:
    """Délais de paiement négociés côté fournisseurs (2 fiches sur ce miroir).

    Le nombre de fiches est remonté tel quel : deux délais négociés ne font pas un
    délai moyen d'entreprise, et l'écran doit pouvoir le dire.
    """
    rows = await _rows("""
        SELECT supplier_id, name, payment_term_name, payment_term_days, credit_limit
        FROM suppliers
    """)
    return [
        {
            "fournisseur_id": r[0],
            "fournisseur": (r[1] or "").strip(),
            "terme": r[2],
            "delai_jours": int(r[3]) if r[3] is not None else None,
            "plafond_credit_xof": round(r[4]) if r[4] is not None else None,
        }
        for r in rows
    ]


# ── Dossiers (marge brute réalisée) ─────────────────────────────────────────

async def fetch_dossiers() -> list[dict]:
    """Dossiers commerciaux : CA et dépense, provisoires et définitifs.

    C'est la seule source de marge du miroir. `depense_definitive` est le champ
    critique : 1 424 dossiers sur 2 408 ne le portent pas, et un dossier sans
    dépense affiche une marge de 100 % — d'où le filtre de couverture appliqué
    dans `budget.py` plutôt qu'ici.
    """
    rows = await _rows("""
        SELECT dossier_ref, client_name, project_name, salesperson, state, date_creation,
               ca_provisoire, ca_definitif, depense_provisoire, depense_definitive,
               marge_provisoire, marge_definitive, perc_marge_definitive,
               montant_recu, reste_a_encaisser, backlog, fournisseurs_restant
        FROM dossiers
    """)
    return [
        {
            "dossier": r[0],
            "client": (r[1] or "").strip() or "(client sans nom)",
            "projet": (r[2] or "").strip(),
            "commercial": (r[3] or "").strip(),
            "etat": r[4] or "",
            "cree_le": str(r[5])[:10] if r[5] else None,
            "ca_provisoire_xof": round(r[6] or 0),
            "ca_definitif_xof": round(r[7] or 0),
            "depense_provisoire_xof": round(r[8] or 0),
            "depense_definitive_xof": round(r[9] or 0),
            "marge_provisoire_xof": round(r[10] or 0),
            "marge_definitive_xof": round(r[11] or 0),
            "taux_marge_definitive_pct": round(r[12] or 0, 1),
            "montant_recu_xof": round(r[13] or 0),
            "reste_a_encaisser_xof": round(r[14] or 0),
            "backlog_xof": round(r[15] or 0),
            "fournisseurs_restant_xof": round(r[16] or 0),
        }
        for r in rows
    ]


# ── Chiffre d'affaires (base du DSO et du taux de marge) ────────────────────

async def fetch_ca_mensuel(annee: int) -> list[dict]:
    """CA signé par mois sur l'exercice — base du DSO en jours de chiffre.

    Le DSO se calcule sur du CA, pas sur des factures : rapporter l'encours au
    seul montant facturé donnerait un délai systématiquement faux dès qu'une part
    du signé n'est pas encore facturée.
    """
    rows = await _rows(f"""
        SELECT CAST(strftime('%m', date_order) AS INTEGER) AS mois,
               COUNT(*) AS nb, SUM(amount) AS montant
        FROM sale_orders
        WHERE date_order IS NOT NULL
          AND strftime('%Y', date_order) = :annee
          AND {_ETATS_CA}
        GROUP BY mois
        ORDER BY mois
    """, {"annee": str(annee)})
    return [{"mois": int(r[0]), "nb_commandes": int(r[1] or 0), "ca_xof": round(r[2] or 0)} for r in rows]


async def fetch_annees_disponibles() -> list[int]:
    """Exercices pour lesquels le miroir porte des factures OU des achats.

    Union volontaire : un exercice qui n'aurait que des achats (charges engagées
    avant facturation) doit rester ouvrable, sinon l'écran budget disparaît pour
    cet exercice sans dire pourquoi.
    """
    rows = await _rows("""
        SELECT DISTINCT annee FROM (
            SELECT strftime('%Y', invoice_date) AS annee FROM invoices WHERE invoice_date IS NOT NULL
            UNION
            SELECT strftime('%Y', date_order) AS annee FROM purchase_orders WHERE date_order IS NOT NULL
            UNION
            SELECT strftime('%Y', date_creation) AS annee FROM dossiers WHERE date_creation IS NOT NULL
        )
        WHERE annee IS NOT NULL
        ORDER BY annee DESC
    """)
    return [int(r[0]) for r in rows if r[0]]
