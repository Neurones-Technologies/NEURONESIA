from abc import ABC, abstractmethod
from typing import Optional

from core.domain.document import GEDEntry, DocumentType


class DocumentRegistry(ABC):
    """Interface pour le registre d'indexation de la GED (suivi des hash et vector_ids)."""

    @abstractmethod
    async def get_entry(self, file_path: str) -> Optional[GEDEntry]:
        """Retourne l'entrée de registre pour un fichier, ou None si jamais indexé."""

    @abstractmethod
    async def upsert_entry(self, entry: GEDEntry) -> None:
        """Crée ou met à jour une entrée dans le registre."""

    @abstractmethod
    async def mark_deleted(self, file_path: str) -> None:
        """Marque un fichier comme supprimé (is_active=False)."""

    @abstractmethod
    async def list_active_entries(self, doc_type: Optional[DocumentType] = None) -> list[GEDEntry]:
        """Liste toutes les entrées actives, filtrées par type si spécifié."""

    @abstractmethod
    async def clear_all(self) -> int:
        """Supprime toutes les entrées du registre (reconstruction à neuf). Retourne le nombre supprimé."""
