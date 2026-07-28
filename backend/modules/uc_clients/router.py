"""Endpoints du portefeuille clients réel (table dossiers) — plus de données
fictives : agrégats réels + profil (activité/recommandations) rédigé par
Claude à partir de ces agrégats, jamais recalculés.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core.services.ttl_cache import cached
from modules.uc_clients.aggregation import detect_signals
from modules.uc_clients.narratif import build_client_profile

router = APIRouter(prefix="/clients", tags=["Clients"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


@router.get("/portfolio")
async def clients_portfolio(request: Request, limit: int = Query(default=30, le=100)):
    portfolio = await _crm(request).get_client_portfolio(limit=limit)
    for c in portfolio:
        c["signaux"] = detect_signals(c)
    return portfolio


@router.get("/dossiers")
async def client_dossiers(request: Request, client: str, year: int | None = Query(default=None)):
    """Historique réel des dossiers d'un client (table dossiers)."""
    return await _crm(request).get_dossiers_by_client(client, year=year)


class ClientProfileRequest(BaseModel):
    client: str


@router.post("/profile")
async def client_profile(request: Request, body: ClientProfileRequest):
    """Rédige l'activité + les recommandations d'un client à partir de ses
    vrais dossiers — Claude ne fait que rédiger, jamais recalculer."""
    dossiers = await _crm(request).get_dossiers_by_client(body.client)
    if not dossiers:
        raise HTTPException(status_code=404, detail="Aucun dossier trouvé pour ce client")

    # CA par dossier = définitif s'il est arrêté, sinon provisoire (estimation) —
    # jamais les deux additionnés (même convention que get_client_portfolio()).
    def _dossier_ca(d: dict) -> float:
        return d["ca_definitif"] if d["ca_definitif"] > 0 else d["ca_provisoire"] or 0

    client_agg = {
        "nb_dossiers": len(dossiers),
        "ca_total_xof": sum(_dossier_ca(d) for d in dossiers),
        "reste_a_encaisser_xof": sum(d["reste_a_encaisser"] or 0 for d in dossiers),
        "backlog_xof": sum(d["backlog"] or 0 for d in dossiers),
    }
    async def _compute():
        dernier = next((d["projet"] for d in dossiers if d["projet"]), None)
        signals = detect_signals(client_agg)
        ctx = {
            "client": body.client,
            "nb_dossiers": client_agg["nb_dossiers"],
            "ca_m": _m(client_agg["ca_total_xof"]),
            "backlog_m": _m(client_agg["backlog_xof"]),
            "reste_m": _m(client_agg["reste_a_encaisser_xof"]),
            "dernier_projet": dernier,
            "constats_list": signals,
        }
        llm = getattr(request.app.state.container, "llm_haiku", None)
        return await build_client_profile(llm, ctx)

    return await cached(("clients_profile", body.client), 900.0, _compute)
