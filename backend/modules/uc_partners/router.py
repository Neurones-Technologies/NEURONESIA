"""Endpoint fournisseurs réel (table purchase_orders, synchronisée depuis
Odoo) — remplace les fixtures (type/spécialité/certifications inventés,
jamais soutenus par une donnée source réelle, ne sont donc pas repris ici)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from modules.uc_daily_analysis import computations as daily_comp
from modules.uc_daily_analysis.store import daily_cached

router = APIRouter(prefix="/partners", tags=["Partners"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


@router.get("/top")
async def top_suppliers(request: Request, limit: int = Query(default=20, le=100)):
    return await _crm(request).get_top_suppliers(limit=limit)


@router.get("/intelligence")
async def supplier_intelligence(request: Request, limit: int = Query(default=20, le=100)):
    """5 indicateurs différenciants (crédit/conso, cash 30-60-90j, marge de
    sous-traitance, fiabilité de paiement, risque de rupture) — cf.
    LocalCRMAdapter.get_supplier_intelligence pour le détail du calcul."""
    return await _crm(request).get_supplier_intelligence(limit=limit)


@router.post("/analysis")
async def partners_analysis(request: Request):
    """Analyse de concentration fournisseurs, rédigée par Claude à partir des
    vrais agrégats déjà calculés (jamais recalculés par le LLM) — figée pour la
    journée par le job du matin (cf. modules/uc_daily_analysis)."""
    llm = getattr(request.app.state.container, "llm_sonnet", None)
    return await daily_cached(
        daily_comp.KEY_PARTNERS,
        "",
        lambda: daily_comp.partners_analysis(_crm(request), llm),
    )
