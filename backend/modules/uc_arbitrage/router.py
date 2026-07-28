"""Module Arbitrages — registre de décisions inter-profils.

Contrairement aux autres modules du cockpit, celui-ci n'existait dans aucun
mirroir Odoo ni dans le blueprint 25 modules d'origine : la « file
d'arbitrage » (dossiers ouverts) est calculée en recoupant des signaux déjà
produits par d'autres modules (impayés × cross-sell/renouvellement), et le
registre de décisions (module 28) persiste dans la table `decisions` — qui
contenait déjà une décision réelle avant ce module (cf. db/models.py).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from api.v1.dependencies import CurrentUser
from modules.uc_arbitrage import aggregation, narratif, store
from modules.uc_crosssell.aggregation import build_montee_valeur

router = APIRouter(prefix="/arbitrage", tags=["Arbitrages"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


async def _compute_candidates(request: Request) -> list[dict]:
    crm = _crm(request)
    unpaid = await crm.get_unpaid_exposure()
    lines = await crm.get_order_lines()
    crosssell = build_montee_valeur(lines)
    portfolio = await crm.get_client_portfolio(limit=200)
    portfolio_by_client = {c["client"]: c for c in portfolio}
    return aggregation.detect_client_conflicts(
        unpaid.get("top_10_debiteurs", []), crosssell, portfolio_by_client,
    )


@router.get("/file")
async def arbitrage_file(request: Request):
    """Module 26 — dossiers ouverts : conflits détectés en temps réel +
    décisions persistées non tranchées."""
    candidates = await _compute_candidates(request)
    open_decisions = await store.list_decisions(status="en_cours")

    now = datetime.utcnow()
    dossiers_ouverts = len(candidates) + len(open_decisions)
    enjeu_cumule = sum(d["enjeu_xof"] for d in candidates) + sum(d["enjeu_xof"] for d in open_decisions)
    cout_report = sum(d["cout_report_xof_semaine"] for d in candidates) + sum(d["cout_report_xof_semaine"] for d in open_decisions)
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


@router.get("/dossier/{subject_ref}")
async def arbitrage_dossier(subject_ref: str, request: Request):
    """Module 27 — détail d'un dossier : positions réelles, deux options
    déterministes, avocat du contraire rédigé par le LLM."""
    candidates = await _compute_candidates(request)
    dossier = next((d for d in candidates if d["subject_ref"] == subject_ref), None)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Aucun dossier d'arbitrage actif pour « {subject_ref} »")

    options = aggregation.build_options(dossier)
    recommandee = next(o for o in options if o["recommandee"])
    llm = getattr(request.app.state.container, "llm_sonnet", None)
    contre = await narratif.build_counter_argument(llm, dossier, recommandee)
    manque = aggregation.missing_info(dossier)
    decisions_liees = await store.list_decisions(subject_ref=subject_ref)

    return {**dossier, "options": options, "contre_arguments": contre, "manque": manque, "decisions_liees": decisions_liees}


@router.post("/decisions")
async def create_decision(payload: dict, current_user: CurrentUser):
    if not payload.get("title"):
        raise HTTPException(status_code=422, detail="Le titre de la décision est requis")
    return await store.create_decision(payload, created_by=current_user.email)


@router.get("/decisions")
async def list_decisions(status: str | None = None, subject_ref: str | None = None):
    """Module 28 — engagements et revues (historique complet, y compris les
    décisions antérieures à ce module)."""
    return await store.list_decisions(status=status, subject_ref=subject_ref)


@router.patch("/decisions/{decision_id}")
async def update_decision(decision_id: int, patch: dict, current_user: CurrentUser):
    decision = await store.update_decision(decision_id, patch)
    if decision is None:
        raise HTTPException(status_code=404, detail="Décision introuvable")
    return decision


@router.get("/reliability")
async def reliability(request: Request):
    """Module 29 — fiabilité des recommandations, calculée sur le registre
    réel de décisions revues (pas de score fabriqué sans historique)."""
    return await store.reliability_stats()
