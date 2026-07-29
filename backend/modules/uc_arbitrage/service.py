"""Assemblage de la file d'arbitrage, hors couche HTTP : le router l'expose,
le briefing quotidien le consomme. `_compute_candidates` vivait dans le
router (donc couplé à `Request`) et n'était pas réutilisable depuis un job
qui n'a pas de contexte FastAPI.
"""
from __future__ import annotations

from datetime import datetime

from modules.uc_arbitrage import aggregation, store
from modules.uc_crosssell.aggregation import build_montee_valeur

# Les entités du groupe (NEURONES*) ne s'arbitrent pas comme un client tiers :
# sans ce filtre, NEURONES TECHNOLOGIES BF représente à elle seule l'essentiel
# de l'enjeu observé, présenté au DG comme de l'enjeu client alors que c'est
# un artefact intra-groupe. Même règle que get_year_stats(exclude_internal=True).
_MOTIF_ENTITE_INTERNE = "NEURONES"


def _est_interne(nom: str) -> bool:
    return _MOTIF_ENTITE_INTERNE in (nom or "").upper()


async def compute_candidates(crm, exclude_internal: bool = False) -> list[dict]:
    unpaid = await crm.get_unpaid_exposure()
    lines = await crm.get_order_lines()
    crosssell = build_montee_valeur(lines)
    portfolio = await crm.get_client_portfolio(limit=200)
    portfolio_by_client = {c["client"]: c for c in portfolio}
    candidats = aggregation.detect_client_conflicts(
        unpaid.get("top_10_debiteurs", []), crosssell, portfolio_by_client,
    )
    if exclude_internal:
        candidats = [d for d in candidats if not _est_interne(d["subject_ref"])]
    return candidats


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


async def compute_file(crm, exclude_internal: bool = False) -> dict:
    """Payload complet de /v1/arbitrage/file : kpi + candidats + décisions
    ouvertes. Corps repris tel quel du router (les deux consommateurs, écran
    et briefing, doivent voir exactement le même calcul)."""
    candidates = await compute_candidates(crm, exclude_internal=exclude_internal)
    open_decisions = await store.list_decisions(status="en_cours")

    now = datetime.utcnow()
    dossiers_ouverts = len(candidates) + len(open_decisions)
    enjeu_cumule = sum(d["enjeu_xof"] for d in candidates) + sum(d["enjeu_xof"] for d in open_decisions)
    cout_report = (
        sum(d["cout_report_xof_semaine"] for d in candidates)
        + sum(d["cout_report_xof_semaine"] for d in open_decisions)
    )
    echeances = [d["due_date"] for d in open_decisions if d["due_date"]]
    jours_echeance = None
    if echeances:
        prochaine = min(datetime.fromisoformat(e) for e in echeances)
        jours_echeance = max((prochaine - now).days, 0)
    revues_en_retard = sum(
        1 for d in open_decisions
        if d["review_date"] and datetime.fromisoformat(d["review_date"]) < now and not d["review_verdict"]
    )

    return {
        "kpi": {
            "dossiers_ouverts": dossiers_ouverts,
            "enjeu_cumule_m_fcfa": _m(enjeu_cumule),
            "echeance_plus_proche_jours": jours_echeance,
            "cout_report_m_fcfa_semaine": round(cout_report / 1_000_000, 1),
            "revues_en_retard": revues_en_retard,
        },
        "candidats": candidates,
        "decisions_ouvertes": open_decisions,
    }
