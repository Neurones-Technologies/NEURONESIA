"""
Chunking contextuel pour les documents semi-structurés (Famille B).
Cibles : CV, offres techniques.

Stratégie :
- Gros chunks (1 500 mots) pour conserver la cohérence du document
- Préfixe de contexte injecté dans chaque chunk à partir des métadonnées extraites
  → "[Ingénieur: Jean Dupont | Rôle: Lead Dev]" pour les CV
  → "[Projet: X | Client: Y]" pour les offres
- Sans ce préfixe, "5 ans d'expérience Go" n'est pas rattaché à une personne.
"""
from core.domain.document import Chunk, DocumentMetadata, DocumentType
from .base import BaseChunker

# Small-to-big : on cherche sur de PETITS enfants (matching précis, embeddés sans
# troncature) et on remonte un PARENT large (contexte complet) au retrieval.
# Le parent garde tout le profil/projet ; l'enfant porte aussi l'en-tête structuré
# pour rester autonome au matching.
_CHILD_SIZE = 200          # mots par enfant (≈ sous la limite 256 tokens de MiniLM)
_CHILD_OVERLAP = 30

_CV_PARENT_SIZE = 1600     # un CV tient en général dans un seul parent
_OFFRE_PARENT_SIZE = 1200  # offres plus longues → plusieurs parents bornés
_PARENT_OVERLAP = 0


def _list_to_str(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value) if value else ""


def _build_cv_header(fields: dict) -> str:
    """
    Construit un en-tête structuré injecté dans CHAQUE chunk du CV.
    Même si le retrieval ne ramène qu'un seul chunk, le LLM voit :
    - Le nom de la personne
    - Son rôle et ses années d'expérience
    - Toutes ses certifications (l'information la plus souvent cherchée)
    - Ses compétences clés
    Cela évite la réponse "la partie certifications n'est pas accessible".
    """
    lines = []
    if fields.get("nom"):
        lines.append(f"Ingénieur : {fields['nom']}")
    if fields.get("role"):
        lines.append(f"Poste     : {fields['role']}")
    if fields.get("experience_years"):
        lines.append(f"Expérience: {fields['experience_years']} ans")

    certs = _list_to_str(fields.get("certifications", []))
    if certs:
        lines.append(f"Certifications: {certs}")

    skills = fields.get("skills", [])
    if isinstance(skills, list) and skills:
        lines.append(f"Compétences   : {', '.join(str(s) for s in skills[:12])}")

    diplomes = _list_to_str(fields.get("diplomes", []))
    if diplomes:
        lines.append(f"Diplômes      : {diplomes}")

    langues = _list_to_str(fields.get("langues", []))
    if langues:
        lines.append(f"Langues       : {langues}")

    if not lines:
        return ""
    return "=== FICHE STRUCTURÉE ===\n" + "\n".join(lines) + "\n=== TEXTE DU CV ===\n"


def _build_offre_prefix(fields: dict) -> str:
    parts = []
    if fields.get("titre"):
        parts.append(f"Projet: {fields['titre']}")
    if fields.get("client"):
        parts.append(f"Client: {fields['client']}")
    if fields.get("statut_gagne") is not None:
        parts.append("Statut: Gagnée" if fields["statut_gagne"] else "Statut: Perdue")
    return f"[{' | '.join(parts)}]\n" if parts else ""


class ContextualChunker(BaseChunker):
    def chunk(self, text: str, doc_id: str, metadata: DocumentMetadata) -> list[Chunk]:
        words = text.split()
        if not words:
            return []

        fields = metadata.extracted_fields or {}

        if metadata.doc_type == DocumentType.CV:
            prefix = _build_cv_header(fields)
            parent_size = _CV_PARENT_SIZE
        else:
            prefix = _build_offre_prefix(fields)
            parent_size = _OFFRE_PARENT_SIZE

        return self._chunk_small_to_big(words, doc_id, metadata, prefix, parent_size)

    def _chunk_small_to_big(
        self,
        words: list[str],
        doc_id: str,
        metadata: DocumentMetadata,
        prefix: str,
        parent_size: int,
    ) -> list[Chunk]:
        """
        Découpe en blocs PARENTS larges (contexte) ; chaque parent est re-découpé en
        petits ENFANTS (matching précis). L'en-tête/préfixe structuré est injecté dans
        le parent ET dans chaque enfant pour qu'ils restent autonomes.
        """
        chunks: list[Chunk] = []
        global_idx = 0
        parent_step = max(1, parent_size - _PARENT_OVERLAP)
        child_step = max(1, _CHILD_SIZE - _CHILD_OVERLAP)

        for p, p_start in enumerate(range(0, len(words), parent_step)):
            block = words[p_start : p_start + parent_size]
            if len(block) < 20:
                continue

            parent_id = f"{doc_id}_p{p}_parent"
            parent_content = prefix + " ".join(block)
            chunks.append(Chunk(
                chunk_id=parent_id,
                doc_id=doc_id,
                content=parent_content,
                token_count=len(parent_content.split()),
                chunk_index=global_idx,
                metadata=metadata,
                is_parent=True,
            ))
            global_idx += 1

            for c_start in range(0, len(block), child_step):
                child_words = block[c_start : c_start + _CHILD_SIZE]
                if len(child_words) < 20:
                    continue
                child_content = prefix + " ".join(child_words)
                chunks.append(Chunk(
                    chunk_id=f"{doc_id}_p{p}_c{global_idx}",
                    doc_id=doc_id,
                    content=child_content,
                    token_count=len(child_content.split()),
                    chunk_index=global_idx,
                    metadata=metadata,
                    parent_chunk_id=parent_id,
                    is_parent=False,
                ))
                global_idx += 1

        return chunks
