"""
Chunking par point à l'ordre du jour pour les documents chronologiques (Famille C).
Cibles : PV de réunion, comptes-rendus.

Stratégie :
- Détecter les marqueurs d'ODJ dans le texte (numérotation, mots-clés)
- Chaque point = 1 chunk autonome, avec métadonnées extraites (décisions, actions, date)
- Évite de mélanger une décision de 2024 avec une de 2026 sur la même requête.
"""
import re
from core.domain.document import Chunk, DocumentMetadata
from .base import BaseChunker

_ODJ_PATTERNS = [
    re.compile(r'^\d+[\.\)]\s+.{3,}', re.IGNORECASE),          # "1. Point XYZ"
    re.compile(r'^point\s+\d+', re.IGNORECASE),                  # "Point 1"
    re.compile(r'^ordre du jour\s*[:\-]?', re.IGNORECASE),       # "Ordre du jour :"
    re.compile(r'^odj\s+\d+', re.IGNORECASE),                    # "ODJ 3"
    re.compile(r'^(?:décision|action|résolution)\s*\d*', re.IGNORECASE),
]

_MIN_BLOCK_WORDS = 15
_FALLBACK_SIZE = 400
_FALLBACK_OVERLAP = 40


def _is_odj_marker(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 150:
        return False
    return any(p.match(line) for p in _ODJ_PATTERNS)


def _split_by_odj(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_header = "Préambule"
    current_lines: list[str] = []

    for line in lines:
        if _is_odj_marker(line) and current_lines:
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

    return sections


class AgendaChunker(BaseChunker):
    def chunk(self, text: str, doc_id: str, metadata: DocumentMetadata) -> list[Chunk]:
        sections = _split_by_odj(text)
        chunks: list[Chunk] = []

        # Enrichir le préfixe avec la date de réunion si disponible
        date_str = ""
        if metadata.extracted_fields.get("date_reunion"):
            date_str = f" | Date: {metadata.extracted_fields['date_reunion']}"

        for idx, (header, body) in enumerate(sections):
            words = body.split()
            if len(words) < _MIN_BLOCK_WORDS:
                continue
            content = f"[PV{date_str} | {header}]\n{body}"
            chunks.append(Chunk(
                chunk_id=f"{doc_id}_odj_{idx}",
                doc_id=doc_id,
                content=content,
                token_count=len(content.split()),
                chunk_index=idx,
                metadata=metadata,
            ))

        # Fallback : aucun marqueur ODJ détecté → chunking plat
        if not chunks:
            words = text.split()
            step = max(1, _FALLBACK_SIZE - _FALLBACK_OVERLAP)
            for i, start in enumerate(range(0, len(words), step)):
                block = words[start : start + _FALLBACK_SIZE]
                if len(block) < _MIN_BLOCK_WORDS:
                    continue
                chunks.append(Chunk(
                    chunk_id=f"{doc_id}_chunk_{i}",
                    doc_id=doc_id,
                    content=" ".join(block),
                    token_count=len(block),
                    chunk_index=i,
                    metadata=metadata,
                ))

        return chunks
