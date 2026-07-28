"""Endpoints du briefing quotidien : lecture (section du rôle courant du
demandeur), statut, et relance manuelle. Le contenu est gelé par le job
planifié de minuit (backend/jobs/scheduler.py) — GET ne régénère jamais,
sauf absence totale de store (tout premier démarrage de l'application).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from api.v1.dependencies import CurrentUser
from modules.uc_briefing import service, store

router = APIRouter(prefix="/briefing", tags=["Briefing"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _llm(request: Request):
    return getattr(request.app.state.container, "llm_sonnet", None)


def _role_of(current_user) -> str:
    role = current_user.role
    return role.value if hasattr(role, "value") else str(role)


@router.get("")
async def get_briefing(request: Request, current_user: CurrentUser):
    payload = store.load()
    if payload is None:
        # Tout premier démarrage : aucun run planifié n'a encore eu lieu.
        payload = await service.generate(_crm(request), _llm(request), triggered_by="cold_start")

    role = _role_of(current_user)
    section = payload.get("sections", {}).get(role)
    return {
        "generated_at": payload.get("generated_at"),
        "triggered_by": payload.get("triggered_by"),
        "role": role,
        "section": section,
    }


@router.get("/status")
async def briefing_status():
    payload = store.load()
    if payload is None:
        return {"generated_at": None, "triggered_by": None, "roles": [], "sections_en_echec": []}
    return {
        "generated_at": payload.get("generated_at"),
        "triggered_by": payload.get("triggered_by"),
        "roles": list(payload.get("sections", {}).keys()),
        "sections_en_echec": payload.get("sections_en_echec", []),
    }


@router.post("/refresh")
async def refresh_briefing(request: Request):
    """Relance manuelle — recalcule les 5 sections immédiatement (hors planning)."""
    payload = await service.generate(_crm(request), _llm(request), triggered_by="manual")
    return {
        "generated_at": payload.get("generated_at"),
        "triggered_by": payload.get("triggered_by"),
        "roles": list(payload.get("sections", {}).keys()),
        "sections_en_echec": payload.get("sections_en_echec", []),
    }
