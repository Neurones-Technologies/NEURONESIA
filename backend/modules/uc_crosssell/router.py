"""Endpoints du module « Montée en valeur » (cross-sell/up-sell/renouvellement/
obsolescence) — calculés sur les vraies commandes (sale_orders.order_lines),
plus aucune donnée fictive.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from modules.uc_crosssell.signals import get_signals
from modules.uc_daily_analysis import computations as daily_comp
from modules.uc_daily_analysis.store import daily_cached

router = APIRouter(prefix="/crosssell", tags=["CrossSell"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


@router.get("/signals")
async def crosssell_signals(request: Request):
    return await get_signals(_crm(request))


@router.post("/analysis")
async def crosssell_analysis(request: Request):
    """Priorisation transversale rédigée par Claude à partir des signaux réels
    déjà calculés (jamais recalculés par le LLM) — figée pour la journée par le
    job du matin (cf. modules/uc_daily_analysis)."""
    llm = getattr(request.app.state.container, "llm_sonnet", None)
    return await daily_cached(
        daily_comp.KEY_CROSSSELL,
        "",
        lambda: daily_comp.crosssell_analysis(_crm(request), llm),
    )
