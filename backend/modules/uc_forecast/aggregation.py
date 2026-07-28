"""Agrégation déterministe du pipeline pondéré pour le module Forecast.

Porte en Python les calculs auparavant faits en JS sur des fixtures
(frontend/lib/fixtures/forecast.ts) : scénarios pessimiste/réaliste/optimiste,
répartition mensuelle et par étape, agrégation par client — désormais sur les
vraies opportunités synchronisées depuis Odoo (table `opportunities`).

Le « risque » et l'horizon mensuel ne sont plus des indicateurs fictifs : le
risque est déduit d'une échéance dépassée sur une opportunité toujours ouverte,
l'horizon mensuel de l'échéance réelle (repli sur l'étape si absente).
"""
from __future__ import annotations

from datetime import date, datetime

_STAGE_MONTH_OFFSET_FALLBACK = {
    "Prospection": 5,
    "Qualification": 4,
    "Montage": 3,
    "Transmise": 3,
    "Proposition": 2,
    "Négociation": 1,
    "Contractualisation": 0,
}

_MONTH_ABBR_FR = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"]


def month_labels() -> list[str]:
    """Les 6 prochains mois (libellés courts fr), à partir du mois courant."""
    today = date.today()
    return [_MONTH_ABBR_FR[(today.month - 1 + i) % 12] for i in range(6)]


def _parse_date(deadline: str | None) -> date | None:
    if not deadline:
        return None
    try:
        return datetime.strptime(deadline[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _month_offset(deadline: str | None, stage: str) -> int:
    """Horizon en mois (0-5) : réel si échéance connue, sinon estimé par l'étape."""
    d = _parse_date(deadline)
    if d is not None:
        today = date.today()
        months = (d.year - today.year) * 12 + (d.month - today.month)
        return max(0, min(5, months))
    return _STAGE_MONTH_OFFSET_FALLBACK.get(stage, 3)


def _at_risk(deadline: str | None) -> bool:
    """Une opportunité encore ouverte dont l'échéance est dépassée est « à risque »."""
    d = _parse_date(deadline)
    return d is not None and d < date.today()


def _age_days(created_at: str | None) -> int | None:
    """Ancienneté en jours depuis la création — calculée ici (pas côté client,
    pour éviter tout écart de rendu serveur/navigateur sur la date du jour)."""
    d = _parse_date(created_at)
    return (date.today() - d).days if d is not None else None


def build_pipeline_forecast(opportunities: list[dict]) -> dict:
    """opportunities : sortie de CRMRepository.list_opportunities() (champs réels)."""
    enriched = []
    for o in opportunities:
        value = o["revenu_attendu_xof"] or 0
        prob = o["probabilite_pct"] or 0
        stage = o["stade"] or "—"
        deadline = o["deadline"]
        enriched.append({
            "name": o["opportunite"],
            "client": o["client"] or "—",
            "stage": stage,
            "value_xof": value,
            "probability_pct": prob,
            "commercial": o["commercial"],
            "deadline": deadline,
            "created_at": o.get("creee_le"),
            "age_days": _age_days(o.get("creee_le")),
            "month_offset": _month_offset(deadline, stage),
            "at_risk": _at_risk(deadline),
            "weighted_xof": value * prob / 100,
        })

    realiste = sum(o["weighted_xof"] for o in enriched)
    pessimiste = sum(o["weighted_xof"] for o in enriched if o["probability_pct"] >= 50)
    optimiste = realiste + sum(o["value_xof"] * 0.5 for o in enriched if o["probability_pct"] < 50)
    total_pipeline = sum(o["value_xof"] for o in enriched)
    avg_prob = round(sum(o["probability_pct"] for o in enriched) / len(enriched)) if enriched else 0

    monthly_realiste = [0.0] * 6
    monthly_pessimiste = [0.0] * 6
    monthly_optimiste = [0.0] * 6
    for o in enriched:
        idx = o["month_offset"]
        monthly_realiste[idx] += o["weighted_xof"]
        monthly_pessimiste[idx] += o["weighted_xof"] if o["probability_pct"] >= 50 else 0
        monthly_optimiste[idx] += o["value_xof"] * 0.5 if o["probability_pct"] < 50 else o["weighted_xof"]

    by_stage: dict[str, float] = {}
    for o in enriched:
        by_stage[o["stage"]] = by_stage.get(o["stage"], 0.0) + o["weighted_xof"]
    stage_entries = sorted(by_stage.items(), key=lambda kv: kv[1], reverse=True)

    by_client: dict[str, dict] = {}
    for o in enriched:
        c = by_client.setdefault(o["client"], {
            "client": o["client"], "opportunities": [], "total_xof": 0.0,
            "weighted_xof": 0.0, "at_risk_xof": 0.0, "min_month_offset": 5,
        })
        c["opportunities"].append(o)
        c["total_xof"] += o["value_xof"]
        c["weighted_xof"] += o["weighted_xof"]
        if o["at_risk"]:
            c["at_risk_xof"] += o["weighted_xof"]
        c["min_month_offset"] = min(c["min_month_offset"], o["month_offset"])
    clients_sorted = sorted(by_client.values(), key=lambda c: c["weighted_xof"], reverse=True)

    return {
        "opportunities": enriched,
        "scenarios": {
            "realiste_xof": round(realiste),
            "pessimiste_xof": round(pessimiste),
            "optimiste_xof": round(optimiste),
            "total_pipeline_xof": round(total_pipeline),
            "avg_probability_pct": avg_prob,
            "nb_opportunites": len(enriched),
        },
        "monthly_buckets": {
            "realiste_xof": [round(v) for v in monthly_realiste],
            "pessimiste_xof": [round(v) for v in monthly_pessimiste],
            "optimiste_xof": [round(v) for v in monthly_optimiste],
        },
        "by_stage": [{"stage": s, "weighted_xof": round(v)} for s, v in stage_entries],
        "by_client": [
            {
                "client": c["client"],
                "nb_opportunites": len(c["opportunities"]),
                "opportunities": c["opportunities"],
                "total_xof": round(c["total_xof"]),
                "weighted_xof": round(c["weighted_xof"]),
                "at_risk_xof": round(c["at_risk_xof"]),
                "min_month_offset": c["min_month_offset"],
            }
            for c in clients_sorted
        ],
    }
