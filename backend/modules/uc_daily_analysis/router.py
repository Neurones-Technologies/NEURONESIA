"""Statut et relance manuelle des analyses IA quotidiennes du cockpit.

Le contenu est figé par le job du matin (`jobs/scheduler.py`) : ces endpoints
servent à vérifier ce qui a été généré aujourd'hui et à forcer un recalcul hors
planning. Ils ne sont jamais appelés par le rendu des cockpits — les sections,
elles, lisent la base via `store.daily_cached` depuis leurs propres endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from api.v1.dependencies import CurrentUser
from modules.uc_daily_analysis import service, store

router = APIRouter(prefix="/daily-analysis", tags=["Analyses quotidiennes"])


def _require_admin(current_user) -> None:
    """La relance déclenche 7 appels Sonnet : réservée aux admins, sinon
    n'importe quel utilisateur pourrait annuler l'économie du calcul quotidien
    en rafraîchissant en boucle."""
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux admins")


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _llm(request: Request):
    return getattr(request.app.state.container, "llm_sonnet", None)


@router.get("/status")
async def daily_analysis_status():
    return {"jour": store.today().isoformat(), "sections": await store.status()}


@router.post("/refresh")
async def refresh_daily_analysis(request: Request, current_user: CurrentUser):
    """Recalcule immédiatement les 7 narrations et remplace celles du jour."""
    _require_admin(current_user)
    return await service.generate_all(_crm(request), _llm(request), triggered_by="manual")
