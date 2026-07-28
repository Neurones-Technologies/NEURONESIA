"""
Route chaque document vers la bonne stratégie de chunking selon son type.

Famille A (structurés rigides)  → HierarchicalChunker
Famille B (semi-structurés)     → ContextualChunker
Famille C (chronologiques)      → AgendaChunker
Défaut                          → FlatChunker
"""
from core.domain.document import Chunk, DocumentMetadata, DocumentType
from .hierarchical import HierarchicalChunker
from .contextual import ContextualChunker
from .agenda import AgendaChunker
from .flat import FlatChunker

_FAMILY_A = {DocumentType.AO, DocumentType.ABE, DocumentType.FICHE_TECHNIQUE, DocumentType.PROCEDURE}
_FAMILY_B = {DocumentType.CV, DocumentType.OFFRE_TECHNIQUE}
_FAMILY_C = {DocumentType.PV_RECETTE, DocumentType.COMPTE_RENDU}


class ChunkingRouter:
    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 60):
        self._hierarchical = HierarchicalChunker()
        self._contextual = ContextualChunker()
        self._agenda = AgendaChunker()
        self._flat = FlatChunker(chunk_size, chunk_overlap)

    def chunk(self, text: str, doc_id: str, metadata: DocumentMetadata) -> list[Chunk]:
        doc_type = metadata.doc_type
        if doc_type in _FAMILY_A:
            return self._hierarchical.chunk(text, doc_id, metadata)
        if doc_type in _FAMILY_B:
            return self._contextual.chunk(text, doc_id, metadata)
        if doc_type in _FAMILY_C:
            return self._agenda.chunk(text, doc_id, metadata)
        return self._flat.chunk(text, doc_id, metadata)
