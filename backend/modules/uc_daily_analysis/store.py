"""Persistance en base des narrations IA de cockpit, figées à la journée.

Remplace le cache mémoire TTL 15 min (core/services/ttl_cache.py) sur les
endpoints `.../analysis` : le résultat survit maintenant aux redémarrages et
n'est calculé qu'une fois par jour, par le job du matin
(`jobs/scheduler.py::_daily_analyses_job`).

Le module lit `AsyncSessionLocal` comme attribut de module — les tests le
remplacent par une fabrique sur base mémoire, comme dans
tests/unit/test_pipeline_snapshot_job.py.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from db.database import AsyncSessionLocal
from db.models import DailyAnalysisModel

logger = logging.getLogger(__name__)

# Rétention : de quoi relire un mois de narrations pour vérifier après coup ce
# qui a été affiché un jour donné, sans laisser la table grossir sans fin.
RETENTION_JOURS = 90

# Un verrou par (clé, variante) : deux profils ouvrant la même section au même
# instant sur une journée non encore générée déclencheraient sinon deux appels
# LLM identiques (marges = DF + DO, cross-sell = DC + AM).
_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def today() -> date:
    """Journée de référence. UTC assumé : Abidjan est à UTC+0, le jour calendaire
    de la base et celui du bureau ne divergent donc jamais."""
    return datetime.now(timezone.utc).date()


def _lock_for(key: str, variant: str) -> asyncio.Lock:
    lock = _LOCKS.get((key, variant))
    if lock is None:
        lock = _LOCKS[(key, variant)] = asyncio.Lock()
    return lock


def _to_payload(row: DailyAnalysisModel) -> dict:
    return {
        "analysis": row.analysis,
        "context": row.context or {},
        "source": row.source,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "triggered_by": row.triggered_by,
    }


async def load(key: str, variant: str = "", day: date | None = None) -> dict | None:
    """Narration figée du jour pour cette section, ou None si pas encore calculée."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(DailyAnalysisModel).where(
                    DailyAnalysisModel.analysis_key == key,
                    DailyAnalysisModel.variant == variant,
                    DailyAnalysisModel.snapshot_date == (day or today()),
                )
            )
        ).scalar_one_or_none()
    return _to_payload(row) if row is not None else None


async def save(
    key: str,
    variant: str,
    payload: dict,
    triggered_by: str,
    day: date | None = None,
) -> dict:
    """Écrit (ou remplace) la narration du jour. Idempotent : une régénération le
    même jour écrase la ligne au lieu d'en ajouter une seconde."""
    snapshot_date = day or today()
    generated_at = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DailyAnalysisModel).where(
                DailyAnalysisModel.analysis_key == key,
                DailyAnalysisModel.variant == variant,
                DailyAnalysisModel.snapshot_date == snapshot_date,
            )
        )
        session.add(
            DailyAnalysisModel(
                analysis_key=key,
                variant=variant,
                snapshot_date=snapshot_date,
                analysis=payload.get("analysis", ""),
                context=payload.get("context") or {},
                source=payload.get("source", "llm"),
                triggered_by=triggered_by,
                generated_at=generated_at,
            )
        )
        await session.commit()
    return {**payload, "generated_at": generated_at.isoformat(), "triggered_by": triggered_by}


def est_figeable(payload: dict) -> bool:
    """Seul un texte réellement rédigé par le modèle est figé pour la journée.

    Un repli déterministe (modèle absent ou en erreur) et un état vide ("aucun
    impayé enregistré") doivent rester recalculables au prochain affichage,
    sinon une panne de quelques minutes gèle le cockpit jusqu'au lendemain.
    """
    return payload.get("source") == "llm" and bool(payload.get("analysis"))


async def daily_cached(
    key: str,
    variant: str,
    compute,
    triggered_by: str = "on_demand",
) -> dict:
    """Lecture de la narration du jour, calculée en secours si elle manque.

    Chemin normal (job du matin déjà passé) : une lecture SQLite, aucun appel
    LLM. Chemin de secours (tout premier démarrage, job en échec, variante
    inédite comme un filtre de période inhabituel) : on calcule, on enregistre,
    et les affichages suivants de la journée relisent la base.
    """
    hit = await load(key, variant)
    if hit is not None:
        return hit

    async with _lock_for(key, variant):
        # Un appel concurrent a pu générer la narration pendant l'attente.
        hit = await load(key, variant)
        if hit is not None:
            return hit

        payload = await compute()
        if not est_figeable(payload):
            logger.info(
                "Analyse quotidienne '%s' (variante %r) non figée — source=%s",
                key, variant, payload.get("source"),
            )
            return {**payload, "generated_at": None, "triggered_by": triggered_by}
        return await save(key, variant, payload, triggered_by)


async def status(day: date | None = None) -> list[dict]:
    """Inventaire des narrations figées pour une journée (endpoint de statut)."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyAnalysisModel)
                .where(DailyAnalysisModel.snapshot_date == (day or today()))
                .order_by(DailyAnalysisModel.analysis_key)
            )
        ).scalars().all()
    return [
        {
            "analysis_key": r.analysis_key,
            "variant": r.variant,
            "source": r.source,
            "triggered_by": r.triggered_by,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "taille_caracteres": len(r.analysis or ""),
        }
        for r in rows
    ]


async def purge_anciennes(retention_jours: int = RETENTION_JOURS) -> int:
    """Supprime les narrations antérieures à la fenêtre de rétention."""
    limite = today() - timedelta(days=retention_jours)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(DailyAnalysisModel).where(DailyAnalysisModel.snapshot_date < limite)
        )
        await session.commit()
    return result.rowcount or 0
