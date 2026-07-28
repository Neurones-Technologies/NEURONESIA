from abc import ABC, abstractmethod
from typing import Optional

from core.domain.document import Chunk, Source


class VectorStore(ABC):
    """Interface abstraite pour le stockage vectoriel dense (ChromaDB → pgvector en prod)."""

    @abstractmethod
    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Insère ou met à jour des chunks avec leurs embeddings."""

    @abstractmethod
    async def search_dense(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: Optional[dict] = None,
    ) -> list[Source]:
        """Recherche sémantique par similarité cosinus."""

    @abstractmethod
    async def delete_by_doc_id(self, doc_id: str) -> None:
        """Supprime tous les chunks d'un document (avant re-indexation)."""

    @abstractmethod
    async def get_doc_ids(self) -> list[str]:
        """Retourne tous les doc_ids indexés."""

    @abstractmethod
    async def inventory(self) -> dict:
        """Inventaire exhaustif : total documents, total chunks, répartition par type."""

    @abstractmethod
    async def delete_orphans(self, valid_doc_ids: set[str]) -> list[str]:
        """Supprime les chunks dont le doc_id n'est pas dans valid_doc_ids. Retourne les ids supprimés."""

    @abstractmethod
    def reset(self) -> None:
        """Vide entièrement le stockage vectoriel (reconstruction à neuf)."""

    # --- Lecture / observabilité ---

    @abstractmethod
    async def get_chunks_by_doc_id(self, doc_id: str) -> list[dict]:
        """Retourne tous les chunks d'un document, triés par chunk_index.
        Chaque élément : {"chunk_id": str, "content": str, "metadata": dict}.
        """

    @abstractmethod
    async def get_by_chunk_ids(self, chunk_ids: list[str]) -> dict[str, dict]:
        """Retourne les chunks demandés indexés par chunk_id.
        Chaque valeur : {"content": str, "metadata": dict}.
        """

    @abstractmethod
    async def get_index_stats(self) -> dict:
        """Statistiques d'agrégation sur l'ensemble des chunks indexés
        (totaux, répartition par type, tailles, comptage par document).
        """

    @abstractmethod
    async def search_dense_debug(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        doc_type: Optional[str] = None,
    ) -> list[dict]:
        """Recherche dense renvoyant le détail par chunk (chunk_id, score, contenu)
        sans dédoublonnage — pour le playground d'inspection.
        """
