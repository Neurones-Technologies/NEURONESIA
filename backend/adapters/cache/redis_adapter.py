import json
import logging
from typing import Any, Optional

from core.ports.cache_store import CacheStore
from config.settings import settings

logger = logging.getLogger(__name__)


class RedisAdapter(CacheStore):
    """Cache Redis — TTL configurable par entrée."""

    def __init__(self):
        self._redis = None
        self._available = False
        self._try_connect()

    def _try_connect(self):
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            self._available = True
            logger.info("Redis connecté sur %s", settings.redis_url)
        except Exception as e:
            logger.warning("Redis non disponible (%s) — cache désactivé", e)
            self._available = False

    async def get(self, key: str) -> Optional[Any]:
        if not self._available or not self._redis:
            return None
        try:
            value = await self._redis.get(key)
            return json.loads(value) if value else None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        if not self._available or not self._redis:
            return
        try:
            await self._redis.setex(key, ttl_seconds, json.dumps(value, default=str))
        except Exception as e:
            logger.debug("Erreur cache set(%s): %s", key, e)

    async def invalidate(self, key: str) -> None:
        if not self._available or not self._redis:
            return
        try:
            await self._redis.delete(key)
        except Exception:
            pass

    async def invalidate_pattern(self, pattern: str) -> None:
        if not self._available or not self._redis:
            return
        try:
            keys = await self._redis.keys(pattern)
            if keys:
                await self._redis.delete(*keys)
        except Exception:
            pass
