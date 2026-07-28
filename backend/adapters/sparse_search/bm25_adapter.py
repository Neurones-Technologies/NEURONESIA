import logging
import pickle
from pathlib import Path

from rank_bm25 import BM25Okapi

from core.ports.sparse_search import SparseSearch
from config.settings import settings

logger = logging.getLogger(__name__)

INDEX_FILE = Path(settings.bm25_index_path) / "bm25.pkl"
META_FILE = Path(settings.bm25_index_path) / "bm25_meta.json"


class BM25Adapter(SparseSearch):
    """BM25 pour la recherche par mots-clés — complète la recherche sémantique dense."""

    def __init__(self):
        self._chunk_ids: list[str] = []
        self._corpus: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._id_set: set[str] = set()  # Dédup O(1) au lieu de `in list` O(N)
        self.load()

    def _tokenize(self, text: str) -> list[str]:
        return text.lower().split()

    def index(self, chunks: list[tuple[str, str]]) -> None:
        added = False
        for chunk_id, content in chunks:
            if chunk_id not in self._id_set:
                self._chunk_ids.append(chunk_id)
                self._corpus.append(self._tokenize(content))
                self._id_set.add(chunk_id)
                added = True
        if added:
            self._rebuild()

    def remove(self, chunk_ids: list[str]) -> None:
        ids_to_remove = set(chunk_ids)
        if not ids_to_remove:
            return
        filtered = [
            (cid, corp)
            for cid, corp in zip(self._chunk_ids, self._corpus)
            if cid not in ids_to_remove
        ]
        if filtered:
            self._chunk_ids, self._corpus = map(list, zip(*filtered))
        else:
            self._chunk_ids, self._corpus = [], []
        self._id_set -= ids_to_remove
        self._rebuild()

    def _rebuild(self):
        if self._corpus:
            self._bm25 = BM25Okapi(self._corpus)
        else:
            self._bm25 = None

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if not self._bm25 or not self._chunk_ids:
            return []
        tokens = self._tokenize(query)
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self._chunk_ids, scores),
            key=lambda x: x[1],
            reverse=True,
        )
        return [(cid, float(score)) for cid, score in ranked[:top_k] if score > 0]

    def save(self) -> None:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX_FILE, "wb") as f:
            pickle.dump((self._chunk_ids, self._corpus), f)
        logger.debug("Index BM25 sauvegardé (%d chunks)", len(self._chunk_ids))

    def clear(self) -> None:
        """Vide l'index BM25 et persiste l'état vide (reconstruction à neuf)."""
        self._chunk_ids, self._corpus, self._id_set = [], [], set()
        self._bm25 = None
        self.save()
        logger.info("Index BM25 réinitialisé (rebuild)")

    def load(self) -> None:
        if INDEX_FILE.exists():
            try:
                with open(INDEX_FILE, "rb") as f:
                    self._chunk_ids, self._corpus = pickle.load(f)
                self._id_set = set(self._chunk_ids)
                self._rebuild()
                logger.info("Index BM25 chargé (%d chunks)", len(self._chunk_ids))
            except Exception as e:
                logger.error("Index BM25 corrompu (%s) — réinitialisation", e)
                self._chunk_ids, self._corpus, self._id_set = [], [], set()
                self._bm25 = None
        else:
            logger.info("Index BM25 vide — sera créé lors de la première indexation")
