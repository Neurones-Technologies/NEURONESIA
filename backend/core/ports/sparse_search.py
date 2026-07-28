from abc import ABC, abstractmethod



class SparseSearch(ABC):
    """Interface pour la recherche par mots-clés (BM25)."""

    @abstractmethod
    def index(self, chunks: list[tuple[str, str]]) -> None:
        """
        Indexe des chunks.
        chunks: list de (chunk_id, content)
        """

    @abstractmethod
    def remove(self, chunk_ids: list[str]) -> None:
        """Supprime des chunks de l'index."""

    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """
        Recherche keyword.
        Retourne: list de (chunk_id, score)
        """

    @abstractmethod
    def save(self) -> None:
        """Persiste l'index sur disque."""

    @abstractmethod
    def load(self) -> None:
        """Charge l'index depuis le disque."""

    @abstractmethod
    def clear(self) -> None:
        """Vide entièrement l'index (reconstruction à neuf)."""
