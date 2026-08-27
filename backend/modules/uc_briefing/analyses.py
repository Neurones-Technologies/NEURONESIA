"""Agrégations propres au briefing, absentes de CRMRepository.

Y vivent les calculs que la trame de briefing réclame et que le miroir permet,
mais qu'aucune méthode du dépôt CRM ne rend : balance âgée, relances du jour,
DSO glissant, dérive budgétaire des dossiers, visibilité du carnet.

Elles ne sont PAS ajoutées à `local_crm_adapter` parce qu'elles répondent à une
question de briefing (« qui dois-je relancer aujourd'hui ? ») et non à une
question de données (« quels sont les impayés ? »). Le dépôt reste un miroir,
ces fonctions sont une lecture.

Chaque fonction rend `mesurable: False` avec une raison plutôt que des zéros
quand sa source manque : c'est ce qui permet aux puces de dire « non mesurable »
au lieu d'afficher un chiffre inventé.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text

from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_OUVERTE = "status != 'cancelled' AND amount_residual > 0 AND due_date IS NOT NULL"


async def _lignes(sql: str, params: dict) -> list:
    async with AsyncSessionLocal() as session:
        return (await session.execute(text(sql), params)).all()


async def balance_agee(as_of: date | None = None, contentieux_jours: int = 90) -> dict:
    """Créances clients ventilées par ancienneté — « qu'est-ce qui reste dû, et
    depuis quand ».

    LES TRANCHES PARTITIONNENT, LE CONTENTIEUX RECOUPE. Les cinq tranches (à
    échoir, 0-30, 30-60, 60-90, 90+) sont fixes et disjointes : leur somme vaut
    exactement le total, et la puce peut les énumérer sans compter deux fois.

    Le contentieux, lui, est un seuil RÉGLABLE par rôle — la DAF le place à
    90 jours, la DG plus tôt — et c'est donc un sous-ensemble TRANSVERSAL, pas
    une sixième tranche. Le traiter comme une tranche paraissait plus simple et
    fonctionnait tant que le seuil valait 90 ; à 30 jours, il recouvrait
    30-60, 60-90 et 90+, et l'énumération de la puce totalisait 145 % de
    l'encours. D'où deux clés distinctes, et un « dont » dans la phrase.

    Deux réserves que toute puce doit porter :
      - 43 % des factures ont une échéance égale à leur date d'émission, ce qui
        sous-estime le retard réel sur cette part du portefeuille (audit §3) ;
      - l'intragroupe est ISOLÉ et non retiré : le total doit rester
        rapprochable de la comptabilité, mais une créance sur une filiale n'est
        pas un risque de même nature qu'une créance externe (audit §4).
    """
    as_of = as_of or date.today()
    p = {"a": as_of.isoformat(), "c": contentieux_jours}
    age = "julianday(date(:a)) - julianday(date(due_date))"

    tranches = {
        "a_echoir": f"{age} < 0",
        "j0_30": f"{age} >= 0 AND {age} <= 30",
        "j30_60": f"{age} > 30 AND {age} <= 60",
        "j60_90": f"{age} > 60 AND {age} <= 90",
        "j90_plus": f"{age} > 90",
    }
    resultat: dict = {"mesurable": True, "as_of": as_of.isoformat(), "tranches": {}}
    for nom, condition in tranches.items():
        ligne = (await _lignes(
            f"SELECT COUNT(*), COALESCE(SUM(amount_residual), 0) FROM invoices "
            f"WHERE {_OUVERTE} AND {condition}", p
        ))[0]
        resultat["tranches"][nom] = {"nb": ligne[0] or 0, "montant_xof": float(ligne[1] or 0)}

    total = (await _lignes(
        f"SELECT COUNT(*), COALESCE(SUM(amount_residual), 0) FROM invoices WHERE {_OUVERTE}", p
    ))[0]
    resultat["nb_total"] = total[0] or 0
    resultat["montant_total_xof"] = float(total[1] or 0)

    # Sous-ensemble transversal, réglé par rôle.
    cont = (await _lignes(
        f"SELECT COUNT(*), COALESCE(SUM(amount_residual), 0) FROM invoices "
        f"WHERE {_OUVERTE} AND {age} > :c", p
    ))[0]
    resultat["contentieux"] = {
        "seuil_jours": contentieux_jours,
        "nb": cont[0] or 0,
        "montant_xof": float(cont[1] or 0),
        "part_pct": (round(float(cont[1] or 0) / resultat["montant_total_xof"] * 100, 1)
                     if resultat["montant_total_xof"] else None),
    }

    intra = (await _lignes(
        "SELECT COUNT(*), COALESCE(SUM(i.amount_residual), 0) FROM invoices i "
        "LEFT JOIN clients c ON c.client_id = i.client_id "
        "WHERE i.status != 'cancelled' AND i.amount_residual > 0 AND i.due_date IS NOT NULL "
        "AND c.name LIKE '%NEURONES%'", p
    ))[0]
    resultat["intragroupe"] = {"nb": intra[0] or 0, "montant_xof": float(intra[1] or 0)}

    resultat["reserve"] = (
        "43 % des factures portent une échéance égale à leur date d'émission — le "
        "retard réel est sous-estimé sur cette part du portefeuille"
    )
    return resultat


async def relances_du_jour(as_of: date | None = None, retard_min_jours: int = 30,
                           limite: int = 5) -> dict:
    """Les créances à relancer aujourd'hui, par client et non par facture.

    Par CLIENT : on ne décroche pas son téléphone cinq fois pour cinq factures du
    même débiteur. Le tri se fait sur le montant cumulé, le retard maximal
    accompagne le nom.
    """
    as_of = as_of or date.today()
    lignes = await _lignes(f"""
        SELECT COALESCE(c.name, '—'), COUNT(*), COALESCE(SUM(i.amount_residual), 0),
               MAX(CAST(julianday(date(:a)) - julianday(date(i.due_date)) AS INTEGER))
        FROM invoices i LEFT JOIN clients c ON c.client_id = i.client_id
        WHERE i.status != 'cancelled' AND i.amount_residual > 0 AND i.due_date IS NOT NULL
          AND julianday(date(:a)) - julianday(date(i.due_date)) > :r
        GROUP BY i.client_id
        ORDER BY SUM(i.amount_residual) DESC
    """, {"a": as_of.isoformat(), "r": retard_min_jours})
    return {
        "mesurable": bool(lignes),
        "retard_min_jours": retard_min_jours,
        "nb_clients": len(lignes),
        "montant_xof": sum(float(l[2] or 0) for l in lignes),
        "top": [
            {"client": l[0], "nb_factures": l[1], "montant_xof": float(l[2] or 0),
             "retard_max_jours": int(l[3] or 0),
             "intragroupe": "NEURONES" in (l[0] or "").upper()}
            for l in lignes[:limite]
        ],
    }


async def dso_glissant(as_of: date | None = None, fenetre_mois: int = 12) -> dict:
    """Délai réel d'encaissement sur douze mois glissants, face aux douze
    précédents.

    Pondéré par les montants, comme l'audit : une moyenne simple donne le même
    poids à une facture de 200 000 F et à une de 500 M. Le ratio encours/CA n'est
    volontairement PAS calculé — appliqué à un exercice en cours il donne 257 j,
    un artefact que l'audit interdit d'afficher.
    """
    as_of = as_of or date.today()
    recul = f"-{fenetre_mois} months"
    recul2 = f"-{fenetre_mois * 2} months"

    async def _fenetre(debut: str, fin: str) -> tuple[int, float | None]:
        ligne = (await _lignes("""
            SELECT COUNT(*),
                   COALESCE(SUM((julianday(date(payment_date)) - julianday(date(invoice_date))) * amount), 0),
                   COALESCE(SUM(amount), 0)
            FROM invoices
            WHERE status != 'cancelled' AND payment_date IS NOT NULL AND invoice_date IS NOT NULL
              AND date(payment_date) > date(:a, :debut) AND date(payment_date) <= date(:a, :fin)
        """, {"a": as_of.isoformat(), "debut": debut, "fin": fin}))[0]
        nb, pondere, base = ligne[0] or 0, float(ligne[1] or 0), float(ligne[2] or 0)
        return nb, (round(pondere / base, 1) if base else None)

    nb_actuel, dso_actuel = await _fenetre(recul, "+0 day")
    nb_precedent, dso_precedent = await _fenetre(recul2, recul)

    if dso_actuel is None:
        return {"mesurable": False,
                "raison": f"aucune facture réglée sur les {fenetre_mois} derniers mois"}
    return {
        "mesurable": True,
        "fenetre_mois": fenetre_mois,
        "dso_jours": dso_actuel,
        "nb_factures": nb_actuel,
        "dso_precedent_jours": dso_precedent,
        "nb_factures_precedent": nb_precedent,
        "ecart_jours": (round(dso_actuel - dso_precedent, 1)
                        if dso_precedent is not None else None),
        # Un DSO calculé sur trois factures n'est pas un DSO. Le seuil est bas
        # (30) mais il évite la pire lecture : « le DSO s'améliore de 40 jours »
        # quand seule une facture rapide a été réglée dans la fenêtre.
        "robuste": nb_actuel >= 30,
    }


async def derive_budgetaire(limite: int = 5, seuil_consommation_pct: float = 90) -> dict:
    """Dossiers dont la dépense constatée dévore la dépense prévue.

    C'est la seule lecture de « mission qui dérive » que les données permettent.
    La lecture canonique de la trame — `qty_delivered` contre `product_uom_qty`
    sur les lignes de commande — est impossible : `qty_delivered` et
    `qty_invoiced` valent 0 sur les 19 510 lignes du miroir. Ici la dérive se lit
    sur le dossier : dépense définitive contre dépense provisoire, et marge
    définitive contre marge prévisionnelle.
    """
    lignes = await _lignes("""
        SELECT dossier_ref, client_name, ca_provisoire, depense_provisoire,
               ca_definitif, depense_definitive,
               perc_marge_previsionnelle, perc_marge_definitive,
               depense_definitive / depense_provisoire * 100.0
        FROM dossiers
        WHERE depense_provisoire > 0 AND depense_definitive > 0
          AND depense_definitive / depense_provisoire * 100.0 >= :s
        ORDER BY depense_definitive DESC
    """, {"s": seuil_consommation_pct})
    return {
        "mesurable": bool(lignes),
        "seuil_consommation_pct": seuil_consommation_pct,
        "nb": len(lignes),
        "depense_engagee_xof": sum(float(l[5] or 0) for l in lignes),
        "top": [
            {"ref": l[0], "client": l[1],
             "ca_provisoire_xof": float(l[2] or 0), "depense_provisoire_xof": float(l[3] or 0),
             "ca_definitif_xof": float(l[4] or 0), "depense_definitive_xof": float(l[5] or 0),
             "marge_prevue_pct": round(float(l[6] or 0), 1),
             "marge_constatee_pct": round(float(l[7] or 0), 1),
             "consommation_pct": round(float(l[8] or 0), 1)}
            for l in lignes[:limite]
        ],
        "reserve": "la dérive se mesure sur la dépense du dossier — les quantités "
                   "livrées des lignes de commande valent 0 dans tout le miroir",
    }


async def sous_traitance_par_dossier(limite: int = 5) -> dict:
    """Engagement fournisseur rapporté au dossier qu'il sert.

    `dossier_id` tient lieu de compte analytique : Odoo n'expose pas
    `account.analytic.line` à l'application, mais porte ce champ maison sur
    `sale.order` ET `purchase.order`. La jointure est donc possible — trouée à
    29 % côté achats (1 521 commandes rattachées sur 2 134), ce que la sortie
    dit plutôt que de le taire.

    Le CA de référence est le DÉFINITIF quand il existe, le provisoire sinon.
    Prendre le provisoire d'office donnait des poids absurdes : sur DC/2024/0232,
    2 M FCFA de CA provisoire pour 1 810 M de définitif faisaient afficher une
    sous-traitance à 33 407 % du CA. Un pourcentage à cinq chiffres dans un
    briefing de direction détruit la crédibilité de toute la page, y compris des
    chiffres justes qui l'entourent.
    """
    lignes = await _lignes("""
        SELECT p.dossier_id, d.client_name, COUNT(*), COALESCE(SUM(p.amount), 0),
               CASE WHEN d.ca_definitif > 0 THEN d.ca_definitif ELSE d.ca_provisoire END,
               CASE WHEN d.ca_definitif > 0 THEN 'définitif' ELSE 'provisoire' END,
               d.perc_marge_provisoire
        FROM purchase_orders p JOIN dossiers d ON d.dossier_ref = p.dossier_id
        WHERE p.state = 'purchase' AND p.dossier_id IS NOT NULL AND p.dossier_id != ''
        GROUP BY p.dossier_id
        ORDER BY SUM(p.amount) DESC
    """, {})
    couverture = (await _lignes("""
        SELECT SUM(CASE WHEN dossier_id IS NOT NULL AND dossier_id != '' THEN 1 ELSE 0 END),
               COUNT(*) FROM purchase_orders WHERE state = 'purchase'
    """, {}))[0]
    rattaches, total = couverture[0] or 0, couverture[1] or 0

    def _ligne(l) -> dict:
        engagement, ca = float(l[3] or 0), float(l[4] or 0)
        return {
            "ref": l[0], "client": l[1], "nb_achats": l[2],
            "engagement_xof": engagement,
            "ca_reference_xof": ca, "base_ca": l[5],
            "marge_provisoire_pct": round(float(l[6] or 0), 1),
            "poids_sur_ca_pct": round(engagement / ca * 100, 1) if ca > 0 else None,
            # Le fait décidable : on a acheté plus que ce que le dossier rapporte.
            # C'est une alerte en soi, à distinguer d'un simple pourcentage élevé.
            "engagement_depasse_ca": bool(ca > 0 and engagement > ca),
        }

    detail = [_ligne(l) for l in lignes]
    return {
        "mesurable": bool(lignes),
        "nb_dossiers": len(lignes),
        "engagement_xof": sum(d["engagement_xof"] for d in detail),
        "couverture_pct": round(rattaches / total * 100, 1) if total else None,
        "nb_achats_orphelins": total - rattaches,
        "nb_engagement_depasse_ca": sum(1 for d in detail if d["engagement_depasse_ca"]),
        "top": detail[:limite],
        "reserve": "le rattachement achat → dossier repose sur `dossier_id`, renseigné "
                   "sur 71 % des commandes d'achat — le reste n'est imputé à aucun dossier",
    }


async def visibilite_carnet(as_of: date | None = None, fenetre_mois: int = 3) -> dict:
    """Combien de mois de facturation le carnet couvre — la question du DG.

    Backlog des dossiers divisé par le CA facturé mensuel moyen des derniers
    mois. Le dénominateur est un facturé RÉEL et non un objectif : aucun n'est
    saisi en base.
    """
    as_of = as_of or date.today()
    ligne = (await _lignes("""
        SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM invoices
        WHERE status != 'cancelled' AND invoice_date IS NOT NULL
          AND date(invoice_date) > date(:a, :recul) AND date(invoice_date) <= date(:a)
    """, {"a": as_of.isoformat(), "recul": f"-{fenetre_mois} months"}))[0]
    facture, nb = float(ligne[0] or 0), ligne[1] or 0
    backlog = float((await _lignes(
        "SELECT COALESCE(SUM(backlog), 0) FROM dossiers", {}))[0][0] or 0)

    moyenne = facture / fenetre_mois if facture else 0
    if not moyenne:
        return {"mesurable": False, "backlog_xof": backlog,
                "raison": f"aucune facture émise sur les {fenetre_mois} derniers mois"}
    return {
        "mesurable": True,
        "backlog_xof": backlog,
        "facture_mensuel_moyen_xof": moyenne,
        "nb_factures_fenetre": nb,
        "fenetre_mois": fenetre_mois,
        "mois_visibilite": round(backlog / moyenne, 1),
    }


async def book_to_bill(as_of: date | None = None, fenetre_mois: int = 12) -> dict:
    """Commandé rapporté au facturé sur la même fenêtre — remplit-on le carnet
    plus vite qu'on ne le vide ?

    Le numérateur est TTC (`amount_untaxed` vaut 0 sur toutes les commandes du
    miroir) et le dénominateur l'est aussi : le ratio est donc homogène, même si
    aucun des deux termes ne l'est au sens comptable. La réserve le dit.
    """
    as_of = as_of or date.today()
    p = {"a": as_of.isoformat(), "recul": f"-{fenetre_mois} months"}
    commande = float((await _lignes("""
        SELECT COALESCE(SUM(amount), 0) FROM sale_orders
        WHERE state IN ('sale', 'done') AND date_order IS NOT NULL
          AND date(date_order) > date(:a, :recul) AND date(date_order) <= date(:a)
    """, p))[0][0] or 0)
    facture = float((await _lignes("""
        SELECT COALESCE(SUM(amount), 0) FROM invoices
        WHERE status != 'cancelled' AND invoice_date IS NOT NULL
          AND date(invoice_date) > date(:a, :recul) AND date(invoice_date) <= date(:a)
    """, p))[0][0] or 0)
    if not facture:
        return {"mesurable": False, "raison": f"aucune facture sur {fenetre_mois} mois"}
    return {
        "mesurable": True,
        "fenetre_mois": fenetre_mois,
        "commande_xof": commande,
        "facture_xof": facture,
        "ratio": round(commande / facture, 2),
        "reserve": "commandé et facturé sont tous deux TTC — le ratio est homogène, "
                   "les montants ne sont pas des bases HT",
    }
