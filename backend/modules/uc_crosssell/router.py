"""Endpoints du module « Montée en valeur » (cross-sell/up-sell/renouvellement/
obsolescence) — calculés sur les vraies commandes (sale_orders.order_lines),
plus aucune donnée fictive.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from core.services.ttl_cache import cached
from modules.uc_crosssell.aggregation import build_montee_valeur
from modules.uc_crosssell.narratif import build_crosssell_analysis

router = APIRouter(prefix="/crosssell", tags=["CrossSell"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _m_fcfa(xof: float) -> int:
    return round(xof / 1_000_000)


@router.get("/signals")
async def crosssell_signals(request: Request):
    lines = await _crm(request).get_order_lines()
    return build_montee_valeur(lines)


@router.post("/analysis")
async def crosssell_analysis(request: Request):
    """Priorisation transversale rédigée par Claude à partir des signaux réels
    déjà calculés (jamais recalculés par le LLM)."""
    lines = await _crm(request).get_order_lines()
    signals = build_montee_valeur(lines)

    all_signals = []
    for key, label in [
        ("renouvellement", "Renouvellement"),
        ("obsolete", "Obsolescence"),
        ("cross_sell", "Cross-sell"),
        ("up_sell", "Up-sell"),
    ]:
        for item in signals[key]:
            all_signals.append({**item, "type": label})

    if not all_signals:
        return {"analysis": "Aucun signal de montée en valeur détecté sur les commandes actuelles."}

    async def _compute():
        top = max(all_signals, key=lambda x: x["montant_xof"])
        ctx = {
            "nb_renouvellement": len(signals["renouvellement"]),
            "nb_obsolete": len(signals["obsolete"]),
            "nb_cross_sell": len(signals["cross_sell"]),
            "nb_up_sell": len(signals["up_sell"]),
            "top_signal_type": top["type"],
            "top_signal_client": top["client"],
            "top_signal_montant": _m_fcfa(top["montant_xof"]),
            "top_signal_detail": top["detail"],
        }
        llm = getattr(request.app.state.container, "llm_sonnet", None)
        analysis = await build_crosssell_analysis(llm, ctx)
        return {"analysis": analysis, "context": ctx}

    return await cached(("crosssell_analysis",), 900.0, _compute)
