from abc import ABC, abstractmethod


class Embedder(ABC):
    """Interface pour la vectorisation de texte."""

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Vectorise une liste de textes. Retourne une liste d'embeddings."""

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Vectorise une requête utilisateur (peut utiliser un modèle distinct)."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimension des vecteurs produits."""
