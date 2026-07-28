"""
EntityResolver — logique PURE de décision de rapprochement (sans I/O).

Étant donné un libellé normalisé et la liste des alias candidats d'un type,
décide : lier à une entité existante, créer une nouvelle entité, ou marquer
pour revue humaine. La persistance est gérée par le KBRepository (adapter),
ce qui rend cette logique testable en isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from core.services.entity_resolution.matching import ratio as _default_ratio
from core.services.entity_resolution.normalize import normalize as _normalize

# Un candidat = (alias_normalisé, entity_id)
Candidate = Tuple[str, str]


@dataclass
class Decision:
    action: str           # "link" | "pending" | "new" | "skip"
    entity_id: Optional[str]
    score: float


class EntityResolver:
    def __init__(
        self,
        auto_threshold: float = 0.90,
        review_threshold: float = 0.75,
        ratio_fn: Callable[[str, str], float] | None = None,
    ):
        self.auto = auto_threshold
        self.review = review_threshold
        self._ratio = ratio_fn or _default_ratio

    def normalize(self, entity_type: str, label) -> str:
        return _normalize(label, entity_type)

    def decide(self, entity_type: str, norm_label: str, candidates: Sequence[Candidate]) -> Decision:
        if not norm_label:
            return Decision("skip", None, 0.0)

        # 1. Correspondance exacte (alias déjà connu) → lien immédiat.
        for alias_norm, eid in candidates:
            if alias_norm == norm_label:
                return Decision("link", eid, 1.0)

        # 2. Meilleur score flou.
        best_id: Optional[str] = None
        best_score = 0.0
        for alias_norm, eid in candidates:
            score = self._ratio(norm_label, alias_norm)
            if score > best_score:
                best_score, best_id = score, eid

        if best_id is not None and best_score >= self.auto:
            return Decision("link", best_id, best_score)
        if best_id is not None and best_score >= self.review:
            return Decision("pending", best_id, best_score)
        return Decision("new", None, best_score)
