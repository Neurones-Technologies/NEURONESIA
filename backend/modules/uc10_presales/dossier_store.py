"""
Persistance des dossiers d'appel d'offres (UC10 Pre-Sales) — condition pour que
« refaire une étape » (analyse, stratégie, offre...) fonctionne même après un
rechargement de page : le fichier source est écrit sur disque et l'état complet
du workflow (forme `AOEntry` du frontend) est répliqué en base (`state` JSON).

`state` est un blob JSON opaque du point de vue du backend (le frontend en est
le seul propriétaire du schéma) — on ne fait que le stocker, le fusionner
(PATCH superficiel) et en extraire quelques colonnes d'index (client_name,
owner, deadline, status) pour filtrer/purger sans désérialiser.

Purge : un dossier dont `deadline` (date "YYYY-MM-DD") est dans le passé est
supprimé automatiquement (ligne DB + fichier disque) par le job planifié
`_presales_expiry_purge_job` (jobs/scheduler.py). Un dossier sans échéance
renseignée n'est jamais purgé automatiquement.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from config.settings import settings
from db.database import AsyncSessionLocal
from db.models import PresalesDossierModel

logger = logging.getLogger(__name__)


def _storage_dir() -> Path:
    return Path(settings.uploads_path) / "presales_ao"


def _safe_filename(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("_")
    return ascii_name or "document"


def save_file(dossier_id: str, filename: str, file_bytes: bytes) -> str:
    """Écrit le fichier AO sur disque et renvoie son chemin (str)."""
    target_dir = _storage_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{dossier_id}_{_safe_filename(filename)}"
    path.write_bytes(file_bytes)
    return str(path)


def read_file(file_path: str) -> bytes | None:
    try:
        p = Path(file_path)
        return p.read_bytes() if p.exists() else None
    except OSError:
        return None


def delete_file(file_path: str) -> None:
    try:
        p = Path(file_path)
        if p.exists():
            p.unlink()
    except OSError as exc:
        logger.warning("Suppression fichier AO échouée (%s) — non bloquant", exc)


async def create(dossier_id: str, filename: str, file_path: str, state: dict) -> dict:
    row = PresalesDossierModel(
        id=dossier_id,
        filename=filename,
        file_path=file_path,
        client_name=str(state.get("clientName") or ""),
        owner=str(state.get("owner") or ""),
        deadline=str(state.get("deadline") or ""),
        status=str(state.get("status") or "pending_analysis"),
        state=state,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
    return state


async def list_all() -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PresalesDossierModel).order_by(PresalesDossierModel.created_at.desc())
        )
        return [row.state for row in result.scalars().all()]


async def get(dossier_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(PresalesDossierModel, dossier_id)
        return row.state if row else None


async def get_file_path(dossier_id: str) -> str | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(PresalesDossierModel, dossier_id)
        return row.file_path if row else None


async def get_file_meta(dossier_id: str) -> tuple[str, str] | None:
    """Renvoie (file_path, filename) du fichier AO original, ou None si le dossier n'existe pas."""
    async with AsyncSessionLocal() as session:
        row = await session.get(PresalesDossierModel, dossier_id)
        return (row.file_path, row.filename) if row else None


async def patch(dossier_id: str, changes: dict) -> dict | None:
    """Fusion superficielle de `changes` dans l'état persisté, puis re-sauvegarde.

    Un `analyze` en arrière-plan peut encore être en train de tourner quand
    l'utilisateur supprime le dossier depuis l'UI : la ligne lue par `session.get`
    ci-dessous a pu disparaître (DELETE d'une autre session) avant le COMMIT de ce
    PATCH, faisant échouer l'UPDATE (0 ligne touchée). Un dossier supprimé n'a plus
    besoin de son résultat — on l'ignore silencieusement plutôt que de laisser
    remonter une StaleDataError en 500."""
    async with AsyncSessionLocal() as session:
        row = await session.get(PresalesDossierModel, dossier_id)
        if row is None:
            return None
        merged = {**row.state, **changes}
        row.state = merged
        if "clientName" in changes:
            row.client_name = str(changes.get("clientName") or "")
        if "owner" in changes:
            row.owner = str(changes.get("owner") or "")
        if "deadline" in changes:
            row.deadline = str(changes.get("deadline") or "")
        if "status" in changes:
            row.status = str(changes.get("status") or "")
        row.updated_at = datetime.utcnow()
        try:
            await session.commit()
        except StaleDataError:
            logger.info(
                "Patch dossier %s ignoré — supprimé entre-temps (analyse en arrière-plan concurrente).",
                dossier_id,
            )
            await session.rollback()
            return None
        return merged


async def delete(dossier_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        row = await session.get(PresalesDossierModel, dossier_id)
        if row is None:
            return False
        file_path = row.file_path
        await session.delete(row)
        await session.commit()
    if file_path:
        delete_file(file_path)
    return True


async def purge_expired(today: date | None = None) -> int:
    """Supprime (ligne + fichier) tout dossier dont l'échéance est dans le passé.

    Un dossier sans échéance (deadline vide) ou avec une échéance illisible n'est
    jamais purgé. `today` est injectable pour les tests.
    """
    today = today or date.today()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PresalesDossierModel).where(PresalesDossierModel.deadline != "")
        )
        rows = result.scalars().all()
        expired = []
        for row in rows:
            try:
                d = datetime.strptime(row.deadline, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d < today:
                expired.append(row)
        for row in expired:
            if row.file_path:
                delete_file(row.file_path)
            await session.delete(row)
        if expired:
            await session.commit()
    if expired:
        logger.info("Purge dossiers présale : %d dossier(s) expiré(s) supprimé(s)", len(expired))
    return len(expired)
