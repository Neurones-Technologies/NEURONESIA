from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DocumentType(str, Enum):
    CV = "cv"
    OFFRE_TECHNIQUE = "offre_technique"
    ABE = "abe"
    PV_RECETTE = "pv_recette"
    PROCEDURE = "procedure"
    FICHE_TECHNIQUE = "fiche_technique"
    COMPTE_RENDU = "compte_rendu"
    AO = "ao"
    CERTIFICATION = "certification"
    TEMPLATE = "template"
    MARCHES_SIMILAIRES = "marches_similaires"
    UNKNOWN = "unknown"


@dataclass
class DocumentMetadata:
    doc_id: str
    filename: str
    doc_type: DocumentType
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    date_document: Optional[datetime] = None
    author: Optional[str] = None
    version: Optional[str] = None
    source_path: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    extracted_fields: dict = field(default_factory=dict)
    contains_pii: bool = False
    pii_categories: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    content: str
    token_count: int
    chunk_index: int
    metadata: DocumentMetadata
    parent_chunk_id: Optional[str] = None
    is_parent: bool = False


@dataclass
class Document:
    doc_id: str
    content: str
    metadata: DocumentMetadata
    hash_sha256: str
    indexed_at: Optional[datetime] = None


@dataclass
class GEDEntry:
    """Entrée dans le registre de la GED (suivi indexation)."""
    doc_id: str
    file_path: str
    hash_sha256: str
    doc_type: DocumentType
    last_indexed: datetime
    vector_ids: list[str] = field(default_factory=list)
    is_active: bool = True


@dataclass
class Source:
    """Référence citée dans une réponse RAG."""
    doc_id: str
    filename: str
    doc_type: DocumentType
    excerpt: str
    relevance_score: float
    page: Optional[int] = None
    chunk_id: Optional[str] = None
    content: Optional[str] = None  # Contenu complet du chunk (pour le contexte LLM) ; excerpt reste court (citations)
    parent_chunk_id: Optional[str] = None  # Si défini, le contexte LLM remonte le parent (small-to-big)
