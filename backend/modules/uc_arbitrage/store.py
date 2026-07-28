"""Persistance du registre de décisions (module Arbitrages) — table `decisions`
(cf. db/models.py::DecisionModel). CRUD direct par session async, comme le
reste du projet pour les tables applicatives (pas de couche repository
supplémentaire ici, la table est simple et le module est seul à l'utiliser).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import DecisionModel


def _to_dict(d: DecisionModel) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "context": d.context,
        "decision_type": d.decision_type,
        "status": d.status,
        "owner": d.owner,
        "due_date": d.due_date.isoformat() if d.due_date else None,
        "outcome": d.outcome,
        "created_by": d.created_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "subject_ref": d.subject_ref,
        "subject_label": d.subject_label,
        "enjeu_xof": d.enjeu_xof,
        "cout_report_xof_semaine": d.cout_report_xof_semaine,
        "mandat_role": d.mandat_role,
        "profils_impliques": d.profils_impliques or [],
        "option_retenue": d.option_retenue,
        "review_date": d.review_date.isoformat() if d.review_date else None,
        "review_verdict": d.review_verdict,
        "review_comment": d.review_comment,
    }


async def create_decision(payload: dict, created_by: str) -> dict:
    async with AsyncSessionLocal() as session:
        decision = DecisionModel(
            title=payload["title"],
            context=payload.get("context", ""),
            decision_type=payload.get("decision_type", "ARBITRAGE"),
            status="en_cours",
            owner=payload.get("owner", created_by),
            due_date=_parse_dt(payload.get("due_date")),
            created_by=created_by,
            created_at=datetime.utcnow(),
            subject_ref=payload.get("subject_ref", ""),
            subject_label=payload.get("subject_label", ""),
            enjeu_xof=float(payload.get("enjeu_xof") or 0),
            cout_report_xof_semaine=float(payload.get("cout_report_xof_semaine") or 0),
            mandat_role=payload.get("mandat_role", ""),
            profils_impliques=payload.get("profils_impliques", []),
            option_retenue=payload.get("option_retenue", ""),
        )
        session.add(decision)
        await session.commit()
        await session.refresh(decision)
        return _to_dict(decision)


async def list_decisions(status: str | None = None, subject_ref: str | None = None) -> list[dict]:
    async with AsyncSessionLocal() as session:
        q = select(DecisionModel).order_by(DecisionModel.created_at.desc())
        if status:
            q = q.where(DecisionModel.status == status)
        if subject_ref:
            q = q.where(DecisionModel.subject_ref == subject_ref)
        result = await session.execute(q)
        return [_to_dict(d) for d in result.scalars()]


async def get_decision(decision_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        decision = await session.get(DecisionModel, decision_id)
        return _to_dict(decision) if decision else None


async def update_decision(decision_id: int, patch: dict) -> dict | None:
    """Trancher / reporter / escalader une décision, ou enregistrer sa revue."""
    async with AsyncSessionLocal() as session:
        decision = await session.get(DecisionModel, decision_id)
        if decision is None:
            return None

        if "status" in patch:
            decision.status = patch["status"]
            if patch["status"] == "tranchee" and decision.decided_at is None:
                decision.decided_at = datetime.utcnow()
        if "outcome" in patch:
            decision.outcome = patch["outcome"]
        if "option_retenue" in patch:
            decision.option_retenue = patch["option_retenue"]
        if "due_date" in patch:
            decision.due_date = _parse_dt(patch["due_date"])
        if "review_date" in patch:
            decision.review_date = _parse_dt(patch["review_date"])
        if "review_verdict" in patch:
            decision.review_verdict = patch["review_verdict"]
        if "review_comment" in patch:
            decision.review_comment = patch["review_comment"]

        await session.commit()
        await session.refresh(decision)
        return _to_dict(decision)


async def reliability_stats() -> dict:
    """Taux de confirmation des décisions revues — cf. module 29 du mockup.
    Historique volontairement affiché comme insuffisant tant que le nombre de
    décisions revues reste faible : pas de score fabriqué sur peu de données."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DecisionModel).where(DecisionModel.review_verdict != "")
        )
        reviewed = list(result.scalars())

    total = len(reviewed)
    confirmed = sum(1 for d in reviewed if d.review_verdict == "confirme")
    return {
        "nb_decisions_revues": total,
        "nb_confirmees": confirmed,
        "taux_confirmation_pct": round(confirmed / total * 100, 1) if total else None,
        "historique_suffisant": total >= 5,
        "note": (
            f"{total} décision(s) revue(s) à ce jour."
            if total >= 5 else
            f"Seulement {total} décision(s) revue(s) — historique insuffisant pour un taux fiable (seuil : 5)."
        ),
    }


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
