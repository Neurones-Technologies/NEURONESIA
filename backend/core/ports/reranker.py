from abc import ABC, abstractmethod


class Reranker(ABC):
    """Re-classement fin des candidats après la fusion (cross-encoder)."""

    @abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Retourne un score de pertinence par document (plus haut = plus pertinent),
        dans le même ordre que `documents`."""
