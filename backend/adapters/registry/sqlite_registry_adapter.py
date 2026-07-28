import logging
from typing import Optional

from sqlalchemy import delete, select, update

from core.ports.document_registry import DocumentRegistry
from core.domain.document import GEDEntry, DocumentType
from db.database import AsyncSessionLocal
from db.models import GEDEntryModel

logger = logging.getLogger(__name__)


class SQLiteRegistryAdapter(DocumentRegistry):
    """Registre d'indexation GED persisté en SQLite."""

    async def get_entry(self, file_path: str) -> Optional[GEDEntry]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(GEDEntryModel).where(GEDEntryModel.file_path == file_path)
            )
            row = result.scalar_one_or_none()
            return self._to_domain(row) if row else None

    async def upsert_entry(self, entry: GEDEntry) -> None:
        async with AsyncSessionLocal() as session:
            existing = await session.get(GEDEntryModel, entry.doc_id)
            if existing:
                existing.hash_sha256 = entry.hash_sha256
                existing.last_indexed = entry.last_indexed
                existing.vector_ids = entry.vector_ids
                existing.is_active = entry.is_active
            else:
                session.add(GEDEntryModel(
                    doc_id=entry.doc_id,
                    file_path=entry.file_path,
                    hash_sha256=entry.hash_sha256,
                    doc_type=entry.doc_type.value,
                    last_indexed=entry.last_indexed,
                    vector_ids=entry.vector_ids,
                    is_active=entry.is_active,
                ))
            await session.commit()

    async def mark_deleted(self, file_path: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(GEDEntryModel)
                .where(GEDEntryModel.file_path == file_path)
                .values(is_active=False)
            )
            await session.commit()

    async def hard_delete(self, file_path: str) -> None:
        """Suppression physique du registre — utilisé pour le droit à l'oubli RGPD (CV)."""
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(GEDEntryModel).where(GEDEntryModel.file_path == file_path)
            )
            await session.commit()

    async def list_active_entries(self, doc_type: Optional[DocumentType] = None) -> list[GEDEntry]:
        async with AsyncSessionLocal() as session:
            query = select(GEDEntryModel).where(GEDEntryModel.is_active == True)  # noqa: E712 (idiome SQLAlchemy)
            if doc_type:
                query = query.where(GEDEntryModel.doc_type == doc_type.value)
            result = await session.execute(query)
            return [self._to_domain(row) for row in result.scalars()]

    async def clear_all(self) -> int:
        async with AsyncSessionLocal() as session:
            result = await session.execute(delete(GEDEntryModel))
            await session.commit()
            return result.rowcount or 0

    @staticmethod
    def _to_domain(model: GEDEntryModel) -> GEDEntry:
        return GEDEntry(
            doc_id=model.doc_id,
            file_path=model.file_path,
            hash_sha256=model.hash_sha256,
            doc_type=DocumentType(model.doc_type),
            last_indexed=model.last_indexed,
            vector_ids=model.vector_ids or [],
            is_active=model.is_active,
        )
