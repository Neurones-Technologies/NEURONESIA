import asyncio
import logging
from functools import lru_cache

from core.ports.embedder import Embedder

logger = logging.getLogger(__name__)


# maxsize=4 : plusieurs modèles peuvent être résidents EN MÊME TEMPS — le modèle legacy
# (presale + indexation) et le modèle FR CamemBERT (chat) sont tous deux actifs. Avec
# maxsize=1 ils s'évinçaient mutuellement et se rechargeaient (~6s) à chaque alternance,
# notamment pendant l'indexation qui embarque chaque document dans les deux cibles.
@lru_cache(maxsize=4)
def _load_model(model_name: str):
    """Charge le modèle une seule fois par nom (lazy, thread-safe via lru_cache)."""
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Chargement sentence-transformers '%s'…", model_name)
        model = SentenceTransformer(model_name)
        logger.info("Modèle '%s' prêt (dim=%d)", model_name, model.get_sentence_embedding_dimension())
        return model
    except ImportError:
        raise RuntimeError(
            "sentence-transformers n'est pas installé. "
            "Lancez : pip install sentence-transformers"
        )


class SentenceTransformersAdapter(Embedder):
    """
    Embeddings locaux via sentence-transformers — aucune clé API requise.
    Modèle par défaut : all-MiniLM-L6-v2 (384 dims, ~80 Mo, CPU-friendly, ~50ms/batch).
    Utilisé en fallback quand OpenAI est indisponible (quota, auth).
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    DEFAULT_DIM = 384

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self._model_name = model_name
        self._dim: int | None = None

    def _get_model(self):
        model = _load_model(self._model_name)
        if self._dim is None:
            self._dim = model.get_sentence_embedding_dimension()
        return model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        model = self._get_model()
        # Exécution dans un thread pour ne pas bloquer la boucle asyncio
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, convert_to_numpy=True, show_progress_bar=False),
        )
        return [e.tolist() for e in embeddings]

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed_texts([query]))[0]

    @property
    def dimension(self) -> int:
        if self._dim is None:
            # Charge le modèle pour connaître la dimension réelle
            self._get_model()
        return self._dim or self.DEFAULT_DIM
