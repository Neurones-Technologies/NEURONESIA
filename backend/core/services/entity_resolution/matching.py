"""
Similarité floue entre libellés normalisés. Renvoie un score [0, 1].

Utilise `rapidfuzz` si disponible (rapide, robuste), sinon repli sur `difflib`
de la stdlib — la couche fonctionne donc dans tous les environnements.
"""
from __future__ import annotations

try:
    from rapidfuzz import fuzz

    def _raw(a: str, b: str) -> float:
        return fuzz.token_sort_ratio(a, b) / 100.0

    BACKEND = "rapidfuzz"
except Exception:  # pragma: no cover - dépend de l'environnement
    from difflib import SequenceMatcher

    def _raw(a: str, b: str) -> float:
        # Tri des tokens → insensible à l'ordre des mots, comme token_sort_ratio.
        a2 = " ".join(sorted(a.split()))
        b2 = " ".join(sorted(b.split()))
        return SequenceMatcher(None, a2, b2).ratio()

    BACKEND = "difflib"


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return _raw(a, b)
