import asyncio
import logging

from core.ports.reranker import Reranker

logger = logging.getLogger(__name__)


class CrossEncoderRerankAdapter(Reranker):
    """
    Reranker cross-encoder local (sentence-transformers).
    Le modèle est chargé PARESSEUSEMENT au premier appel (téléchargement éventuel),
    pour ne pas peser au démarrage et rester optionnel.
    """

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info("Chargement du reranker cross-encoder : %s", self._model_name)
            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        model = await asyncio.to_thread(self._load)
        pairs = [[query, doc] for doc in documents]
        scores = await asyncio.to_thread(model.predict, pairs)
        return [float(s) for s in scores]
