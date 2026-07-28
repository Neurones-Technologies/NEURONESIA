"""Endpoint fournisseurs réel (table purchase_orders, synchronisée depuis
Odoo) — remplace les fixtures (type/spécialité/certifications inventés,
jamais soutenus par une donnée source réelle, ne sont donc pas repris ici)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from core.services.ttl_cache import cached
from modules.uc_partners.narratif import build_partners_analysis

router = APIRouter(prefix="/partners", tags=["Partners"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


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
    vrais agrégats déjà calculés (jamais recalculés par le LLM)."""
    suppliers = await _crm(request).get_top_suppliers(limit=50)
    if not suppliers:
        return {"analysis": "Aucune commande fournisseur enregistrée actuellement."}

    async def _compute():
        total = sum(s["montant_total_xof"] for s in suppliers)
        top = suppliers[0]
        ctx = {
            "total_m": _m(total),
            "nb_fournisseurs": len(suppliers),
            "top_nom": top["name"],
            "top_montant_m": _m(top["montant_total_xof"]),
            "top_part_pct": round(top["montant_total_xof"] / total * 100) if total else 0,
            "top_nb_commandes": top["nb_commandes"],
            "top_derniere_commande": top["derniere_commande"] or "non renseignée",
        }
        llm = getattr(request.app.state.container, "llm_sonnet", None)
        analysis = await build_partners_analysis(llm, ctx)
        return {"analysis": analysis, "context": ctx}

    return await cached(("partners_analysis",), 900.0, _compute)
