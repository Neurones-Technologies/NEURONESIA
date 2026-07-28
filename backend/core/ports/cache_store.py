from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheStore(ABC):
    """Interface pour le cache (Redis en prod, in-memory en test)."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Retourne la valeur ou None si absente / expirée."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        """Stocke une valeur avec TTL."""

    @abstractmethod
    async def invalidate(self, key: str) -> None:
        """Supprime une entrée du cache."""

    @abstractmethod
    async def invalidate_pattern(self, pattern: str) -> None:
        """Supprime toutes les entrées correspondant à un pattern (ex: 'client:*')."""
