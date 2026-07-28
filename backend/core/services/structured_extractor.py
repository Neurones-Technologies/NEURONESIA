"""
StructuredExtractor — extraction typée, validée et scorée d'un document.

S'ajoute AU pipeline existant : il réutilise la même cascade LLM
(`agentic_step`, tool_use) que le MetadataExtractor, mais produit un objet
Pydantic validé destiné à la base relationnelle `kb_*`. Un échec ici ne doit
jamais interrompre l'indexation vectorielle (l'appelant l'enveloppe en try/except).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from core.domain.document import DocumentType
from core.ports.llm_gateway import LLMGateway
from core.services.extraction.schemas import CONTENT_MODELS
from core.services.extraction.tools import TOOLS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Tu es un extracteur de données documentaires pour une entreprise d'ingénierie. "
    "Lis le document et appelle OBLIGATOIREMENT l'outil fourni avec les informations extraites. "
    "Recopie les valeurs telles qu'elles apparaissent (montants, dates, noms). "
    "Si une information est absente, utilise null ou une liste vide. "
    "Ne génère AUCUN texte libre, seulement l'appel d'outil."
)


@dataclass
class ExtractionResult:
    doc_type: DocumentType
    payload: BaseModel          # instance Pydantic validée (CVExtraction, AOExtraction, …)
    raw: dict                   # entrée brute renvoyée par le LLM (audit)
    score_confiance: float      # 0.0–1.0
    revue_humaine: bool         # True si score < seuil


class StructuredExtractor:
    def __init__(
        self,
        llm: LLMGateway,
        confidence_threshold: float = 0.6,
        text_limit: int = 8000,
        max_tokens: int = 2000,
    ):
        self._llm = llm
        self._threshold = confidence_threshold
        self._text_limit = text_limit
        self._max_tokens = max_tokens

    async def extract(self, text: str, doc_type: DocumentType) -> ExtractionResult | None:
        """
        Renvoie un ExtractionResult validé, ou None si le type n'est pas géré,
        si le LLM n'appelle pas l'outil, ou si la validation échoue.
        """
        tool = TOOLS.get(doc_type)
        model_cls = CONTENT_MODELS.get(doc_type)
        if tool is None or model_cls is None:
            return None

        try:
            step = await self._llm.agentic_step(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text[: self._text_limit]}],
                tools=[tool],
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            logger.warning("StructuredExtractor — appel LLM échoué (%s) : %s", doc_type.value, exc)
            return None

        if not step.tool_calls:
            logger.warning("StructuredExtractor — aucun tool_call pour %s", doc_type.value)
            return None

        raw = step.tool_calls[0].get("input", {}) or {}
        try:
            payload = model_cls.model_validate(raw)
        except ValidationError as exc:
            logger.warning("StructuredExtractor — validation Pydantic échouée (%s) : %s",
                           doc_type.value, exc)
            return None

        score = self._confidence(payload)
        return ExtractionResult(
            doc_type=doc_type,
            payload=payload,
            raw=raw,
            score_confiance=score,
            revue_humaine=score < self._threshold,
        )

    @staticmethod
    def _confidence(payload: BaseModel) -> float:
        """Heuristique simple : proportion de champs de tête réellement renseignés."""
        data = payload.model_dump(exclude={"type"})
        total = filled = 0
        for value in data.values():
            total += 1
            if value not in (None, "", [], {}):
                filled += 1
        return round(filled / total, 2) if total else 0.0
