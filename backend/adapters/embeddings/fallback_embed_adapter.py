import asyncio
import logging

from core.ports.embedder import Embedder

logger = logging.getLogger(__name__)

# Mots-clés dans le message d'erreur qui indiquent un problème de quota/accès
_QUOTA_KEYWORDS = ("quota", "rate_limit", "ratelimit", "billing", "insufficient", "credit", "429")


def _is_quota_error(exc: Exception) -> bool:
    msg = f"{type(exc).__name__} {exc}".lower()
    return any(kw in msg for kw in _QUOTA_KEYWORDS)


class FallbackEmbedAdapter(Embedder):
    """
    Essaie l'embedder primaire (OpenAI). Si une erreur de quota / authentification
    est détectée, bascule définitivement sur l'embedder de fallback (sentence-transformers local).

    ⚠️  Si les dimensions diffèrent (ex. OpenAI 1536 → local 384), ChromaDB va détecter
    le changement et recréer sa collection automatiquement. Tous les documents devront
    être réindexés via le bouton 'Réindexer' de l'interface.
    """

    def __init__(self, primary: Embedder, fallback: Embedder):
        self._primary = primary
        self._fallback = fallback
        self._using_fallback = False
        # Sérialise UNIQUEMENT la première sonde du primaire : sans ça, un burst d'appels
        # concurrents (ex. 8 recherches CV en parallèle) tape tous OpenAI et récolte chacun
        # un 429 avant que le flag ne se pose → tempête de 429. Une fois sondé, le happy path
        # (OpenAI vivant) repart en parallèle sans verrou.
        self._probed = False
        self._probe_lock = asyncio.Lock()

    # ── API publique ──────────────────────────────────────────────────────────

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self._using_fallback:
            return await self._fallback.embed_texts(texts)

        # Tant qu'on n'a pas sondé le primaire une première fois, on sérialise : un seul
        # appel teste OpenAI, les autres attendent le verdict pour ne pas multiplier les 429.
        if not self._probed:
            async with self._probe_lock:
                if self._using_fallback:
                    return await self._fallback.embed_texts(texts)
                if not self._probed:
                    return await self._embed_primary_or_fallback(texts, first_probe=True)
            # sortie du verrou : primaire jugé vivant → on continue en parallèle ci-dessous

        return await self._embed_primary_or_fallback(texts, first_probe=False)

    async def _embed_primary_or_fallback(self, texts: list[str], first_probe: bool) -> list[list[float]]:
        try:
            result = await self._primary.embed_texts(texts)
            self._probed = True
            return result
        except Exception as exc:
            if _is_quota_error(exc):
                if not self._using_fallback:
                    logger.warning(
                        "OpenAI embeddings indisponibles (quota/auth) → bascule définitive sur "
                        "le modèle local pour la session. Cause : %s", exc,
                    )
                self._using_fallback = True
                self._probed = True
                return await self._fallback.embed_texts(texts)
            raise

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed_texts([query]))[0]

    @property
    def dimension(self) -> int:
        return self._fallback.dimension if self._using_fallback else self._primary.dimension

    # ── Infos de debug ────────────────────────────────────────────────────────

    @property
    def active_model(self) -> str:
        return "local (sentence-transformers)" if self._using_fallback else "openai"

    def reset_to_primary(self) -> None:
        """Force le retour vers OpenAI (utile après rechargement des crédits)."""
        self._using_fallback = False
        self._probed = False  # re-sonder OpenAI au prochain appel
        logger.info("FallbackEmbedAdapter : retour au modèle primaire OpenAI")
