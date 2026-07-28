"""
DocumentClassifier — détermine le type d'un document parmi les 6 types
extractibles (playbook §3) : cv, appel_offres, compte_rendu, certification,
pv_recette, attestation_bonne_execution.

Usage : FALLBACK. Le type est normalement déduit du dossier par le GEDWatcher ;
ce classifieur n'intervient que lorsque le type est UNKNOWN, afin de ne jamais
écraser une inférence par dossier fiable.

Stratégie : règles rapides (nom de fichier + tête du texte, sans appel API),
puis classification LLM si les règles ne tranchent pas.
"""
from __future__ import annotations

import logging
import re

from core.domain.document import DocumentType
from core.ports.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

# Libellés présentés au LLM → type interne. Les libellés sont explicites
# (≠ tokens cryptiques « ao »/« abe ») pour fiabiliser la classification.
_LABEL_TO_TYPE: dict[str, DocumentType] = {
    "cv": DocumentType.CV,
    "appel_offres": DocumentType.AO,
    "compte_rendu": DocumentType.COMPTE_RENDU,
    "certification": DocumentType.CERTIFICATION,
    "pv_recette": DocumentType.PV_RECETTE,
    "attestation_bonne_execution": DocumentType.ABE,
}

# Règles ordonnées : la première qui matche gagne. Conçues pour la PRÉCISION
# (mieux vaut laisser le LLM trancher que produire un faux positif).
_RULES: list[tuple[re.Pattern, DocumentType]] = [
    (re.compile(r"attestation\s+de\s+bonne\s+(?:ex[ée]cution|fin)|bonne\s+ex[ée]cution\s+des\s+prestations", re.I), DocumentType.ABE),
    (re.compile(r"proc[èe]s[\s\-]*verbal\s+de\s+recette|pv\s+de\s+recette|r[ée]ception\s+(?:provisoire|d[ée]finitive)", re.I), DocumentType.PV_RECETTE),
    (re.compile(r"appel\s+d['’]?offres?|avis\s+d['’]?appel|dossier\s+d['’]?appel|cahier\s+des\s+charges", re.I), DocumentType.AO),
    (re.compile(r"compte[\s\-]*rendu|ordre\s+du\s+jour|relev[ée]\s+de\s+d[ée]cisions", re.I), DocumentType.COMPTE_RENDU),
    (re.compile(r"curriculum\s+vitae|exp[ée]riences?\s+professionnelles?|\bcv\b", re.I), DocumentType.CV),
    (re.compile(r"\bce\s+certificat\b|certificat\s+n[°o]|atteste\s+que\b.*certif|certifi[ée]\s+(?:que|par)", re.I), DocumentType.CERTIFICATION),
]


class DocumentClassifier:
    def __init__(self, llm: LLMGateway, text_limit: int = 4000):
        self._llm = llm
        self._text_limit = text_limit

    async def classify(self, text: str, filename: str | None = None) -> DocumentType:
        guess = self._classify_rules(text, filename)
        if guess is not None:
            logger.debug("Classifieur (règles) → %s", guess.value)
            return guess

        try:
            label = await self._llm.classify(
                text[: self._text_limit], list(_LABEL_TO_TYPE.keys())
            )
        except Exception as exc:
            logger.warning("Classifieur LLM échoué : %s", exc)
            return DocumentType.UNKNOWN

        return _LABEL_TO_TYPE.get(label, DocumentType.UNKNOWN)

    def _classify_rules(self, text: str, filename: str | None) -> DocumentType | None:
        head = (text or "")[:3000]
        haystack = f"{filename or ''}\n{head}"
        for pattern, doc_type in _RULES:
            if pattern.search(haystack):
                return doc_type
        return None
