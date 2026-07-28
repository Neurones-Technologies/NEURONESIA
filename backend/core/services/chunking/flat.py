from core.domain.document import Chunk, DocumentMetadata
from .base import BaseChunker


class FlatChunker(BaseChunker):
    """Chunking par mots, sans analyse de structure. Comportement par défaut."""

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 60):
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(self, text: str, doc_id: str, metadata: DocumentMetadata) -> list[Chunk]:
        words = text.split()
        if not words:
            return []
        chunks = []
        step = max(1, self._chunk_size - self._chunk_overlap)
        for i, start in enumerate(range(0, len(words), step)):
            chunk_words = words[start : start + self._chunk_size]
            if len(chunk_words) < 20:
                continue
            chunks.append(Chunk(
                chunk_id=f"{doc_id}_chunk_{i}",
                doc_id=doc_id,
                content=" ".join(chunk_words),
                token_count=len(chunk_words),
                chunk_index=i,
                metadata=metadata,
            ))
        return chunks
