"""
Port de persistance de la couche structurée (knowledge base relationnelle `kb_*`).

L'implémentation concrète (SQLite) écrit les faits typés dans les tables `kb_*`
de façon idempotente par `doc_id`. Indépendant du moteur de stockage.
"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.domain.document import DocumentType

if TYPE_CHECKING:
    from core.services.structured_extractor import ExtractionResult


class KBRepository(ABC):
    @abstractmethod
    async def save_extraction(
        self,
        *,
        doc_id: str,
        doc_type: DocumentType,
        fichier_source: str,
        hash_sha256: str,
        result: "ExtractionResult",
        page: int | None = None,
    ) -> None:
        """
        Persiste un résultat d'extraction validé. DOIT être idempotent :
        ré-écrire le même doc_id remplace les lignes existantes (pas de doublon).
        """

    @abstractmethod
    async def delete_by_doc_id(self, doc_id: str) -> None:
        """Supprime tous les faits structurés rattachés à un document."""

    # ── Résolution d'entités (Phase 2) ──────────────────────────────────────

    @abstractmethod
    async def resolve_document(self, doc_id: str, doc_type: DocumentType, resolver) -> None:
        """
        Résout les entités (clients/personnes/projets) référencées par un document
        et renseigne ses `*_ref_id`. `resolver` expose `normalize()` et `decide()`.
        Idempotent : ré-exécuter ne crée pas de doublon d'entité.
        """

    @abstractmethod
    async def resolve_all(self, resolver) -> int:
        """Backfill : résout tous les documents déjà extraits. Renvoie le nombre traité."""

    @abstractmethod
    async def list_pending(self, entity_type: str | None = None) -> list[dict]:
        """Liste les rapprochements en attente de revue humaine."""

    @abstractmethod
    async def confirm_alias(self, alias_id: int, entity_id: str | None = None) -> None:
        """Valide un alias en revue : status→confirmed (et lie à `entity_id` si fourni)."""
