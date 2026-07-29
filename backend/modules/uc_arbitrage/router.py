"""Module Arbitrages — registre de décisions inter-profils.

Contrairement aux autres modules du cockpit, celui-ci n'existait dans aucun
mirroir Odoo ni dans le blueprint 25 modules d'origine : la « file
d'arbitrage » (dossiers ouverts) est calculée en recoupant des signaux déjà
produits par d'autres modules (impayés × cross-sell/renouvellement), et le
registre de décisions (module 28) persiste dans la table `decisions` — qui
contenait déjà une décision réelle avant ce module (cf. db/models.py).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.v1.dependencies import CurrentUser
from modules.uc_arbitrage import aggregation, narratif, service, store

router = APIRouter(prefix="/arbitrage", tags=["Arbitrages"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


async def _compute_candidates(request: Request) -> list[dict]:
    return await service.compute_candidates(_crm(request))


@router.get("/file")
async def arbitrage_file(request: Request):
    """Module 26 — dossiers ouverts : conflits détectés en temps réel +
    décisions persistées non tranchées."""
    return await service.compute_file(_crm(request))


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
