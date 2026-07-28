"""
Chunking hiérarchique parent-enfant pour les documents structurés (Famille A).
Cibles : AO, fiches techniques, procédures.

Stratégie :
- Détecter les titres de section dans le texte brut via heuristiques
- Chaque section → 1 chunk "parent" (texte complet de la section)
- Chaque section → N chunks "enfants" (découpés par mots, plus petits)
- Les enfants portent parent_chunk_id → le moteur de retrieval peut remonter le parent pour le LLM
"""
import re
from core.domain.document import Chunk, DocumentMetadata
from .base import BaseChunker

_SECTION_PATTERNS = [
    re.compile(r'^(?:article|section|chapitre|partie|titre)\s+\d+', re.IGNORECASE),
    re.compile(r'^\d+[\.\)]\s+\S'),          # "1. Titre" ou "1) Titre"
    re.compile(r'^\d+\.\d+[\.\)]?\s+\S'),    # "1.1 Sous-titre" ou "1.1."
    re.compile(r'^[A-ZÀ-Ü][A-ZÀ-Ü\s\-]{6,60}$'),  # Ligne TOUT EN MAJUSCULES
    re.compile(r'^(?:I|II|III|IV|V|VI|VII|VIII|IX|X)[\.\)]\s+\S', re.IGNORECASE),  # Romain
]

_CHILD_SIZE = 200   # mots par chunk enfant
_CHILD_OVERLAP = 20


def _is_section_header(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 120:
        return False
    return any(p.match(line) for p in _SECTION_PATTERNS)


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Retourne une liste (titre_section, contenu_section)."""
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_header = "Document"
    current_lines: list[str] = []

    for line in lines:
        if _is_section_header(line) and current_lines:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_header, body))
            current_header = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_header, body))

    # Fallback : aucune section détectée → on renvoie le document entier
    if not sections:
        sections.append(("Document", text.strip()))

    return sections


def _word_chunks(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    step = max(1, size - overlap)
    result = []
    for start in range(0, len(words), step):
        block = words[start : start + size]
        if len(block) >= 15:
            result.append(" ".join(block))
    return result


class HierarchicalChunker(BaseChunker):
    def chunk(self, text: str, doc_id: str, metadata: DocumentMetadata) -> list[Chunk]:
        sections = _split_sections(text)
        all_chunks: list[Chunk] = []
        global_idx = 0

        for sec_idx, (header, body) in enumerate(sections):
            parent_id = f"{doc_id}_sec_{sec_idx}_parent"
            parent_content = f"[Section: {header}]\n{body}"

            # Chunk parent (toute la section)
            all_chunks.append(Chunk(
                chunk_id=parent_id,
                doc_id=doc_id,
                content=parent_content,
                token_count=len(parent_content.split()),
                chunk_index=global_idx,
                metadata=metadata,
                is_parent=True,
            ))
            global_idx += 1

            # Chunks enfants (pour la recherche précise)
            children = _word_chunks(body, _CHILD_SIZE, _CHILD_OVERLAP)
            for child_text in children:
                prefixed = f"[Section: {header}] {child_text}"
                all_chunks.append(Chunk(
                    chunk_id=f"{doc_id}_sec_{sec_idx}_child_{global_idx}",
                    doc_id=doc_id,
                    content=prefixed,
                    token_count=len(prefixed.split()),
                    chunk_index=global_idx,
                    metadata=metadata,
                    parent_chunk_id=parent_id,
                    is_parent=False,
                ))
                global_idx += 1

        return all_chunks
