"""Lectures SQL du miroir pour le pilotage commercial — aucun calcul métier ici.

Ces requêtes attaquent directement les tables du miroir via `AsyncSessionLocal`
plutôt que de passer par le port `CRMRepository`, contrairement au reste des
modules cockpit. Trois raisons assumées :

1. Le port est une ABC : y ajouter une méthode abstraite casse l'instanciation de
   `OdooAdapter` tant qu'il ne l'implémente pas. Onze nouvelles lectures pour un
   seul profil ne justifient pas d'élargir un contrat partagé par cinq profils.
2. Ces lectures sont SPÉCIFIQUES au DC (rythme mensuel par compte, complétude
   d'opportunité, mouvement entre deux instantanés). Placées dans l'adapter,
   elles y seraient du code mort pour tous les autres profils.
3. Le miroir local EST la source dans les deux configurations : `container.py`
   câble `LocalCRMAdapter` et le job de synchronisation Odoo écrit dans ces mêmes
   tables. Lire `sale_orders` ici ou via l'adapter interroge le même SQLite.

Les lectures déjà couvertes par le port (segmentation de dormance, forecast
pondéré, CA par commercial) sont réutilisées telles quelles et NON réécrites ici.

Le filtre d'étape close se fait par MOTIF (`LIKE '%gagn%'`), jamais par égalité :
le référentiel Odoo porte 16 libellés pour ~9 étapes réelles (« 6-Gagné » et
« Won » coexistent, « 8-Suspendu » et « 8- Suspendu » aussi). Comparer par
égalité perdrait silencieusement 681 affaires gagnées.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text

from db.database import AsyncSessionLocal

# Étapes closes, détectées par sous-chaîne sur `lower(stage)`. Repris à
# l'identique de `local_crm_adapter.get_account_activity` pour que « ouvert »
# veuille dire la même chose dans les deux modules.
_CLOS = (
    "lower(COALESCE(stage, '')) NOT LIKE '%gagn%' "
    "AND lower(COALESCE(stage, '')) NOT LIKE '%won%' "
    "AND lower(COALESCE(stage, '')) NOT LIKE '%perdu%' "
    "AND lower(COALESCE(stage, '')) NOT LIKE '%lost%' "
    "AND lower(COALESCE(stage, '')) NOT LIKE '%annul%' "
    "AND lower(COALESCE(stage, '')) NOT LIKE '%cancel%'"
)

# Commandes retenues pour le CA : mêmes états que le reste du cockpit.
_ETATS_CA = "state IN ('sale', 'done')"


async def _rows(sql: str, params: dict | None = None) -> list:
    async with AsyncSessionLocal() as session:
        return (await session.execute(text(sql), params or {})).fetchall()


# ── Opportunités ─────────────────────────────────────────────────────────────

async def fetch_opportunites() -> list[dict]:
    """Toutes les opportunités avec les champs de COMPLÉTUDE et de datation.

    Distincte de `list_all_opportunities()` de l'adapter, qui ne remonte ni
    `opp_id` (impossible d'identifier une ligne), ni `date_closed`/`write_date`
    (impossible de mesurer une durée de cycle), ni `client_id`.
    """
    rows = await _rows("""
        SELECT opp_id, name, client_id, client_name, stage, expected_revenue,
               probability, salesperson_name, deadline, created_at, date_closed,
               write_date, offer_family
        FROM opportunities
    """)
    return [
        {
            "opp_id": r[0],
            "name": r[1] or "(opportunité sans libellé)",
            "client_id": r[2],
            "client": r[3] or "",
            "stage": r[4] or "",
            "montant_xof": round(r[5] or 0),
            "probabilite_pct": round(r[6] or 0),
            "commercial": r[7] or "",
            "deadline": str(r[8])[:10] if r[8] else None,
            "creee_le": str(r[9])[:10] if r[9] else None,
            "close_le": str(r[10])[:10] if r[10] else None,
            "modifiee_le": str(r[11])[:10] if r[11] else None,
            "famille": r[12] or "",
        }
        for r in rows
    ]


# ── Rythme de commande par compte (pics d'activité) ──────────────────────────

async def fetch_series_mensuelles_par_compte() -> list[dict]:
    """Nombre et montant de commandes par compte ET par mois.

    C'est la seule série qui permette de mesurer un pic : le pic se définit par
    rapport au passé du compte, pas dans l'absolu. Le groupement se fait par
    `client_id` et non par nom (641 identifiants pour 632 noms — UEMOA en porte 3,
    les fusionner mêlerait des comptes distincts) ; le nom canonique est repris de
    la commande la plus récente.
    """
    rows = await _rows(f"""
        WITH nom AS (
            SELECT client_id, client_name FROM (
                SELECT client_id, client_name,
                       ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date_order DESC) rg
                FROM sale_orders
                WHERE client_name IS NOT NULL AND client_name != ''
            ) WHERE rg = 1
        )
        SELECT o.client_id,
               COALESCE(NULLIF(TRIM(c.name), ''), n.client_name, '(compte sans nom)') AS compte,
               strftime('%Y-%m', o.date_order) AS mois,
               COUNT(*) AS nb,
               SUM(o.amount) AS montant,
               MAX(o.salesperson_name) AS commercial
        FROM sale_orders o
        LEFT JOIN nom n ON n.client_id = o.client_id
        LEFT JOIN clients c ON c.client_id = o.client_id
        WHERE o.client_id IS NOT NULL AND o.client_id != '' AND o.{_ETATS_CA}
        GROUP BY o.client_id, mois
        ORDER BY o.client_id, mois
    """)
    return [
        {
            "client_id": r[0],
            "compte": r[1],
            "mois": r[2],
            "nb": int(r[3] or 0),
            "montant_xof": round(r[4] or 0),
            "commercial": r[5] or "",
        }
        for r in rows
    ]


# ── CA réalisé, ventilé pour la cadence mensuelle / trimestrielle / annuelle ──

async def fetch_ca_mensuel_par_commercial(annee: int) -> list[dict]:
    """CA signé par commercial et par mois d'une année — socle du Gap.

    Le commercial reste ici en TEXTE BRUT : sa normalisation relève de
    `referentiel.py`, qui seul connaît les alias et les comptes techniques.
    """
    rows = await _rows(f"""
        SELECT COALESCE(NULLIF(TRIM(salesperson_name), ''), '(non renseigné)') AS commercial,
               CAST(strftime('%m', date_order) AS INTEGER) AS mois,
               COUNT(*) AS nb,
               SUM(amount) AS ca
        FROM sale_orders
        WHERE {_ETATS_CA} AND strftime('%Y', date_order) = :annee
        GROUP BY commercial, mois
    """, {"annee": str(annee)})
    return [
        {"commercial": r[0], "mois": int(r[1] or 0), "nb": int(r[2] or 0), "ca_xof": round(r[3] or 0)}
        for r in rows
    ]


async def fetch_annees_disponibles() -> list[int]:
    """Années pour lesquelles le miroir porte des commandes, décroissant."""
    rows = await _rows(f"""
        SELECT DISTINCT CAST(strftime('%Y', date_order) AS INTEGER) AS a
        FROM sale_orders WHERE {_ETATS_CA} AND date_order IS NOT NULL
        ORDER BY a DESC
    """)
    return [int(r[0]) for r in rows if r[0]]


# ── Instantanés du pipeline (mouvement réel du pipe) ─────────────────────────

async def fetch_dates_snapshots() -> list[str]:
    rows = await _rows("SELECT DISTINCT snapshot_date FROM pipeline_snapshots ORDER BY snapshot_date")
    return [str(r[0])[:10] for r in rows]


async def fetch_mouvements_pipe(depuis: str, jusqu_a: str) -> dict:
    """Comparaison de deux instantanés : étapes et montants qui ont bougé.

    Sert à dire au DC ce que le traçage du cycle de vie peut ou ne peut pas lui
    apprendre AUJOURD'HUI. Sur les deux instantanés disponibles (28/07 et
    11/08/2026), une seule opportunité sur 9 475 a changé d'étape : le résultat
    doit être affiché tel quel, y compris quand il dit que rien ne bouge.
    """
    rows = await _rows("""
        SELECT a.opp_id, a.name, a.client_name, a.stage, b.stage,
               a.expected_revenue, b.expected_revenue, b.salesperson_name
        FROM pipeline_snapshots a
        JOIN pipeline_snapshots b ON a.opp_id = b.opp_id
        WHERE a.snapshot_date = :depuis AND b.snapshot_date = :jusqu_a
    """, {"depuis": depuis, "jusqu_a": jusqu_a})
    suivies = len(rows)
    etape, montant = [], []
    for r in rows:
        if (r[3] or "") != (r[4] or ""):
            etape.append({
                "opp_id": r[0], "name": r[1] or "", "client": r[2] or "",
                "etape_avant": r[3] or "", "etape_apres": r[4] or "",
                "montant_xof": round(r[5] or 0), "commercial": r[7] or "",
            })
        if round(r[5] or 0) != round(r[6] or 0):
            montant.append({
                "opp_id": r[0], "name": r[1] or "", "client": r[2] or "",
                "montant_avant_xof": round(r[5] or 0), "montant_apres_xof": round(r[6] or 0),
                "commercial": r[7] or "",
            })
    return {
        "depuis": depuis,
        "jusqu_a": jusqu_a,
        "nb_suivies": suivies,
        "changements_etape": etape,
        "changements_montant": montant,
    }


# ── Noms de commerciaux observés (référentiel) ───────────────────────────────

async def fetch_noms_commerciaux() -> list[dict]:
    """Chaque orthographe observée, avec ses tables d'origine et son volume."""
    rows = await _rows("""
        SELECT nom, SUM(nb) AS occurrences, GROUP_CONCAT(src) AS sources FROM (
            SELECT TRIM(salesperson_name) AS nom, COUNT(*) AS nb, 'opportunities' AS src
            FROM opportunities WHERE salesperson_name IS NOT NULL AND TRIM(salesperson_name) != ''
            GROUP BY nom
            UNION ALL
            SELECT TRIM(salesperson_name) AS nom, COUNT(*) AS nb, 'sale_orders' AS src
            FROM sale_orders WHERE salesperson_name IS NOT NULL AND TRIM(salesperson_name) != ''
            GROUP BY nom
        ) GROUP BY nom ORDER BY occurrences DESC
    """)
    return [
        {"nom": r[0], "occurrences": int(r[1] or 0), "sources": sorted(set((r[2] or "").split(",")))}
        for r in rows
    ]


async def fetch_lignes_sans_commercial() -> dict:
    rows = await _rows("""
        SELECT (SELECT COUNT(*) FROM opportunities
                WHERE salesperson_name IS NULL OR TRIM(salesperson_name) = ''),
               (SELECT COUNT(*) FROM sale_orders
                WHERE salesperson_name IS NULL OR TRIM(salesperson_name) = '')
    """)
    r = rows[0]
    return {"opportunites": int(r[0] or 0), "commandes": int(r[1] or 0)}


# ── Qualité du référentiel clients (analyse sectorielle) ────────────────────

async def fetch_couverture_secteur() -> dict:
    """Taux de renseignement de `clients.sector` — mesuré, jamais supposé.

    C'est ce chiffre qui décide si l'analyse sectorielle est calculable. Il est
    renvoyé même (surtout) quand il est mauvais : le cockpit doit dire pourquoi
    un écran est vide.
    """
    rows = await _rows("""
        SELECT COUNT(*),
               SUM(CASE WHEN sector IS NOT NULL AND TRIM(sector) != '' THEN 1 ELSE 0 END),
               COUNT(DISTINCT CASE WHEN sector IS NOT NULL AND TRIM(sector) != '' THEN sector END)
        FROM clients
    """)
    total, remplis, distincts = (int(x or 0) for x in rows[0])
    valeurs = await _rows("""
        SELECT TRIM(sector), COUNT(*) FROM clients
        WHERE sector IS NOT NULL AND TRIM(sector) != '' GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """)
    return {
        "nb_clients": total,
        "nb_avec_secteur": remplis,
        "nb_secteurs_distincts": distincts,
        "couverture_pct": round(100 * remplis / total, 2) if total else 0.0,
        "valeurs": [{"secteur": v[0], "nb_clients": int(v[1])} for v in valeurs],
    }


# ── Veille marché ────────────────────────────────────────────────────────────

async def fetch_veille(limit: int = 40) -> dict:
    """Signaux de veille externes + leur qualité de collecte.

    Les entrées sans URL sont du bruit de scraping (libellés de menu capturés
    comme titres) : elles sont comptées dans `qualite`, jamais servies comme
    signal. Une veille dont on ne dit pas le taux de déchet se lit comme un
    panorama de marché — elle n'en est pas un.
    """
    rows = await _rows("""
        SELECT e.id, e.title, e.url, e.description, e.published_at, e.detected_at,
               e.country, e.relevance_score, e.axe, e.signal_label, e.risque, e.offre,
               e.criticite, e.priority, e.so_what, e.action_suggeree, s.name
        FROM veille_entries e
        LEFT JOIN veille_sources s ON s.id = e.source_id
        ORDER BY COALESCE(e.criticite, 0) DESC, e.detected_at DESC
        LIMIT :limit
    """, {"limit": limit})
    entrees = [
        {
            "id": int(r[0]),
            "titre": (r[1] or "").strip()[:300],
            "url": r[2] or "",
            "detecte_le": str(r[5])[:10] if r[5] else None,
            "publie_le": str(r[4])[:10] if r[4] else None,
            "pays": r[6] or "",
            "axe": r[8] or "",
            "signal": r[9] or "",
            "risque": r[10] or "",
            "offre": r[11] or "",
            "criticite": int(r[12] or 0),
            "so_what": r[14] or "",
            "action": r[15] or "",
            "source": r[16] or "",
        }
        for r in rows
    ]
    stats = await _rows("""
        SELECT COUNT(*),
               SUM(CASE WHEN url IS NOT NULL AND url != '' THEN 1 ELSE 0 END),
               SUM(CASE WHEN published_at IS NOT NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN axe IS NOT NULL AND axe != '' THEN 1 ELSE 0 END),
               MIN(detected_at), MAX(detected_at)
        FROM veille_entries
    """)
    s = stats[0]
    sources = await _rows("SELECT name, url, active, last_scan FROM veille_sources ORDER BY id")
    return {
        "entrees": entrees,
        "qualite": {
            "nb_total": int(s[0] or 0),
            "nb_avec_url": int(s[1] or 0),
            "nb_avec_date_publication": int(s[2] or 0),
            "nb_avec_axe": int(s[3] or 0),
            "premier_scan": str(s[4])[:10] if s[4] else None,
            "dernier_scan": str(s[5])[:10] if s[5] else None,
        },
        "sources": [
            {"nom": r[0] or "", "url": r[1] or "", "active": bool(r[2]), "dernier_scan": str(r[3])[:10] if r[3] else None}
            for r in sources
        ],
    }


# ── Tables de pilotage (objectifs, axes, alertes, référentiel) ───────────────

async def fetch_objectifs(annee: int | None = None) -> list[dict]:
    """Objectifs en vigueur — les révisions périmées sont écartées ici."""
    sql = """
        SELECT id, scope, scope_ref, kind, period_type, period_year, period_index,
               target_amount_xof, target_count, revision, note, created_by, created_at
        FROM commercial_objectives WHERE superseded = 0
    """
    params: dict = {}
    if annee is not None:
        sql += " AND period_year = :annee"
        params["annee"] = annee
    sql += " ORDER BY period_year DESC, period_type, period_index, scope, scope_ref"
    rows = await _rows(sql, params)
    return [
        {
            "id": int(r[0]), "scope": r[1], "scope_ref": r[2] or "", "kind": r[3],
            "period_type": r[4], "period_year": int(r[5] or 0), "period_index": int(r[6] or 0),
            "target_amount_xof": round(r[7] or 0), "target_count": int(r[8] or 0),
            "revision": int(r[9] or 1), "note": r[10] or "", "created_by": r[11] or "",
            "created_at": str(r[12])[:19] if r[12] else None,
        }
        for r in rows
    ]


async def fetch_axes_mappings() -> list[dict]:
    rows = await _rows("""
        SELECT axis, match_type, pattern, priority FROM strategic_axis_mappings
        WHERE is_active = 1 ORDER BY priority, id
    """)
    return [{"axe": r[0], "match_type": r[1], "pattern": r[2], "priority": int(r[3] or 100)} for r in rows]


async def upsert_axes_mappings(mappings: list[dict], par: str) -> int:
    """Sème la grille de lecture par défaut si la table est vide. Idempotent.

    Ne remplace JAMAIS des motifs existants : dès que le DC en a édité un, la
    grille lui appartient et le code n'a plus à la réécrire.
    """
    existants = await fetch_axes_mappings()
    if existants:
        return 0
    async with AsyncSessionLocal() as session:
        for m in mappings:
            await session.execute(text("""
                INSERT INTO strategic_axis_mappings (axis, match_type, pattern, priority, is_active, created_by, created_at)
                VALUES (:axis, :mt, :pattern, :prio, 1, :par, :now)
            """), {
                "axis": m["axe"], "mt": m.get("match_type", "contains"), "pattern": m["pattern"],
                "prio": m.get("priority", 100), "par": par, "now": datetime.utcnow(),
            })
        await session.commit()
    return len(mappings)


async def fetch_referentiel_commerciaux() -> tuple[list[dict], list[dict]]:
    people = await _rows("""
        SELECT salesperson_id, display_name, is_active, note FROM salespeople ORDER BY display_name
    """)
    aliases = await _rows("""
        SELECT alias_normalized, alias_raw, salesperson_id, confirmed, occurrences, source_tables
        FROM salesperson_aliases ORDER BY occurrences DESC
    """)
    return (
        [{"salesperson_id": r[0], "display_name": r[1], "is_active": bool(r[2]), "note": r[3] or ""} for r in people],
        [
            {
                "alias_normalized": r[0], "alias_raw": r[1], "salesperson_id": r[2],
                "confirmed": bool(r[3]), "occurrences": int(r[4] or 0),
                "source_tables": json.loads(r[5]) if isinstance(r[5], str) else (r[5] or []),
            }
            for r in aliases
        ],
    )


async def persist_referentiel(people: list[dict], aliases: list[dict]) -> dict:
    """Écrit le référentiel PROPOSÉ par la normalisation, sans écraser l'humain.

    Une ligne d'alias déjà `confirmed` n'est jamais retouchée : la normalisation
    automatique propose, l'humain tranche, et sa décision est définitive. Seules
    les occurrences (un compteur, pas un arbitrage) sont rafraîchies.
    """
    _, existants = await fetch_referentiel_commerciaux()
    deja = {a["alias_normalized"]: a for a in existants}
    now = datetime.utcnow()
    crees_p = crees_a = maj_a = 0
    async with AsyncSessionLocal() as session:
        for p in people:
            exists = (await session.execute(
                text("SELECT 1 FROM salespeople WHERE salesperson_id = :id"), {"id": p["salesperson_id"]}
            )).fetchone()
            if exists:
                continue
            await session.execute(text("""
                INSERT INTO salespeople (salesperson_id, display_name, is_active, note, created_at, updated_at)
                VALUES (:id, :nom, :actif, :note, :now, :now)
            """), {
                "id": p["salesperson_id"], "nom": p["display_name"], "actif": 1 if p.get("is_active", True) else 0,
                "note": p.get("note", ""), "now": now,
            })
            crees_p += 1
        for a in aliases:
            ancien = deja.get(a["alias_normalized"])
            if ancien is None:
                await session.execute(text("""
                    INSERT INTO salesperson_aliases
                        (alias_normalized, alias_raw, salesperson_id, confirmed, source_tables,
                         occurrences, first_seen_at, resolved_by)
                    VALUES (:norm, :raw, :sid, 0, :src, :occ, :now, '')
                """), {
                    "norm": a["alias_normalized"], "raw": a["alias_raw"], "sid": a.get("salesperson_id"),
                    "src": json.dumps(a.get("source_tables", [])), "occ": a.get("occurrences", 0), "now": now,
                })
                crees_a += 1
            elif not ancien["confirmed"]:
                await session.execute(text("""
                    UPDATE salesperson_aliases SET occurrences = :occ, salesperson_id = :sid, source_tables = :src
                    WHERE alias_normalized = :norm
                """), {
                    "occ": a.get("occurrences", 0), "sid": a.get("salesperson_id"),
                    "src": json.dumps(a.get("source_tables", [])), "norm": a["alias_normalized"],
                })
                maj_a += 1
        await session.commit()
    return {"commerciaux_crees": crees_p, "alias_crees": crees_a, "alias_maj": maj_a}


async def sync_alertes(alertes: list[dict]) -> list[dict]:
    """Enregistre la PREMIÈRE apparition de chaque clé et rend l'état persistant.

    Retourne les alertes enrichies de `depuis` (date de première apparition) et
    de `ecartee`. Les alertes disparues ne sont pas supprimées : leur ligne reste,
    ce qui permettra plus tard de dire « ce compte a déjà alerté trois fois ».
    """
    if not alertes:
        return []
    cles = [a["alert_key"] for a in alertes]
    marqueurs = ",".join(f":k{i}" for i in range(len(cles)))
    params = {f"k{i}": k for i, k in enumerate(cles)}
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(
            f"SELECT alert_key, created_at, dismissed_at, dismissed_reason, read_at "
            f"FROM commercial_alerts WHERE alert_key IN ({marqueurs})"
        ), params)).fetchall()
        etat = {
            r[0]: {
                "depuis": str(r[1])[:10] if r[1] else None,
                "ecartee": r[2] is not None,
                "motif_ecart": r[3] or "",
                "lue": r[4] is not None,
            }
            for r in rows
        }
        for a in alertes:
            if a["alert_key"] in etat:
                continue
            await session.execute(text("""
                INSERT INTO commercial_alerts
                    (alert_key, alert_type, severity, subject_ref, subject_label,
                     salesperson_id, montant_xof, payload, created_at, dismissed_reason)
                VALUES (:key, :type, :sev, :ref, :label, :sid, :mnt, :payload, :now, '')
            """), {
                "key": a["alert_key"], "type": a["alert_type"], "sev": a["severity"],
                "ref": a.get("subject_ref", ""), "label": a.get("subject_label", "")[:500],
                "sid": a.get("salesperson_id"), "mnt": a.get("montant_xof", 0),
                "payload": json.dumps(a.get("payload", {})), "now": now,
            })
            etat[a["alert_key"]] = {"depuis": now.date().isoformat(), "ecartee": False, "motif_ecart": "", "lue": False}
        await session.commit()
    return [{**a, **etat.get(a["alert_key"], {})} for a in alertes]


async def ecarter_alerte(alert_key: str, motif: str) -> bool:
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("""
            UPDATE commercial_alerts SET dismissed_at = :now, dismissed_reason = :motif
            WHERE alert_key = :key AND dismissed_at IS NULL
        """), {"now": datetime.utcnow(), "motif": motif[:500], "key": alert_key})
        await session.commit()
        return (res.rowcount or 0) > 0
