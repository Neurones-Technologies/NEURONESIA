import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert

from db.database import AsyncSessionLocal
from db.models import QuarantineModel

logger = logging.getLogger(__name__)


@dataclass
class QuarantineEntry:
    id: int
    file_path: str
    doc_type: str
    reason: str
    quarantined_at: datetime
    retry_count: int
    file_size_bytes: int
    text_length: int


class QuarantineAdapter:
    async def add(
        self,
        file_path: str,
        doc_type: str,
        reason: str,
        file_size_bytes: int = 0,
        text_length: int = 0,
    ) -> None:
        # Normaliser en chemin absolu résolu : un même fichier physique enregistré
        # via des chemins différents (absolu vs relatif) ne crée plus de doublon.
        file_path = str(Path(file_path).resolve())
        async with AsyncSessionLocal() as session:
            stmt = (
                insert(QuarantineModel)
                .values(
                    file_path=file_path,
                    doc_type=doc_type,
                    reason=reason,
                    file_size_bytes=file_size_bytes,
                    text_length=text_length,
                    quarantined_at=datetime.utcnow(),
                    retry_count=0,
                )
                .on_conflict_do_update(
                    index_elements=["file_path"],
                    set_={
                        "reason": reason,
                        "retry_count": QuarantineModel.retry_count + 1,
                        "quarantined_at": datetime.utcnow(),
                        "text_length": text_length,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()
        logger.warning("Quarantaine : %s — %s", Path(file_path).name, reason)

    async def list_all(self) -> list[QuarantineEntry]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuarantineModel).order_by(QuarantineModel.quarantined_at.desc())
            )
            rows = result.scalars().all()
        return [
            QuarantineEntry(
                id=r.id,
                file_path=r.file_path,
                doc_type=r.doc_type,
                reason=r.reason,
                quarantined_at=r.quarantined_at,
                retry_count=r.retry_count,
                file_size_bytes=r.file_size_bytes,
                text_length=r.text_length,
            )
            for r in rows
        ]

    async def remove(self, file_path: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(QuarantineModel).where(QuarantineModel.file_path == file_path)
            )
            await session.commit()

    async def remove_resolved(self, file_path: str) -> int:
        """Supprime TOUTES les entrées dont le chemin résout vers le même fichier
        physique (gère les doublons absolu/relatif). Retourne le nb supprimé."""
        target = str(Path(file_path).resolve())
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(QuarantineModel))
            ids = [r.id for r in result.scalars().all() if str(Path(r.file_path).resolve()) == target]
            if ids:
                await session.execute(delete(QuarantineModel).where(QuarantineModel.id.in_(ids)))
                await session.commit()
        return len(ids)

    async def purge_expired(self, retention_days: int) -> list[str]:
        """Supprime les entrées plus vieilles que retention_days (dernière tentative).
        Retourne les file_path concernés pour que l'appelant supprime aussi les fichiers.
        retention_days <= 0 → désactivé."""
        if retention_days <= 0:
            return []
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuarantineModel).where(QuarantineModel.quarantined_at < cutoff)
            )
            paths = [r.file_path for r in result.scalars().all()]
            if paths:
                await session.execute(
                    delete(QuarantineModel).where(QuarantineModel.quarantined_at < cutoff)
                )
                await session.commit()
        return paths
