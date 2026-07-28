"""Tests de la logique de décision du EntityResolver (Phase 2).

Le score flou est injecté (ratio_fn) pour rendre les seuils déterministes,
indépendamment du backend (rapidfuzz/difflib).
"""
from core.services.entity_resolver import EntityResolver


def _resolver(score_for_c1):
    # ratio renvoie `score_for_c1` quand on compare au candidat « c1 », sinon 0.
    return EntityResolver(ratio_fn=lambda a, b: score_for_c1 if b == "c1" else 0.0)


CANDS = [("c1", "E1"), ("c2", "E2")]


def test_exact_match_lie_immediatement():
    r = _resolver(0.0)
    d = r.decide("client", "c2", CANDS)
    assert d.action == "link" and d.entity_id == "E2" and d.score == 1.0


def test_score_eleve_lien_auto():
    d = _resolver(0.95).decide("client", "x", CANDS)
    assert d.action == "link" and d.entity_id == "E1"


def test_score_intermediaire_pending():
    d = _resolver(0.80).decide("client", "x", CANDS)
    assert d.action == "pending" and d.entity_id == "E1"


def test_score_faible_nouvelle_entite():
    d = _resolver(0.50).decide("client", "x", CANDS)
    assert d.action == "new" and d.entity_id is None


def test_aucun_candidat_nouvelle_entite():
    d = _resolver(0.99).decide("client", "x", [])
    assert d.action == "new"


def test_label_vide_skip():
    d = _resolver(0.99).decide("client", "", CANDS)
    assert d.action == "skip"
