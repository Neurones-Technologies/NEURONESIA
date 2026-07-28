from abc import ABC, abstractmethod

from core.domain.document import Chunk, DocumentMetadata


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, text: str, doc_id: str, metadata: DocumentMetadata) -> list[Chunk]:
        ...
