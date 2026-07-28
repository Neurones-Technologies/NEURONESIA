"""Pré-validation IA de conformité (UC10) — dérivation déterministe + extension domaine."""
from core.domain.offer import (
    ScoringResult, ScoringCriterion, Risk, MatchedDocument, BidRecommendation,
)
from core.domain.requirements import (
    Exigence, MatriceConformite,
    TYPE_CRITERE, TYPE_PROFIL, TYPE_SEUIL,
    STATUT_A_TRAITER, STATUT_CONFORME, STATUT_CONFORME_PARTIEL, STATUT_NON_CONFORME,
)
from modules.uc10_presales.conformity import derive_suggested_status, assess_matrice


def _scoring(**kw) -> ScoringResult:
    base = dict(
        ao_filename="ao.pdf", summary="résumé", key_elements=[], matched_documents=[],
        gaps_analysis="", strengths=[], risks=[], score=60,
        recommendation=BidRecommendation.GO, justification="",
    )
    base.update(kw)
    return ScoringResult(**base)


def _ex(texte, type_=TYPE_CRITERE, blocking=False):
    return Exigence(id="EX-0001", texte=texte, type=type_, blocking=blocking)


def test_critere_haute_note_est_conforme():
    sc = _scoring(criteria_breakdown=[
        ScoringCriterion(id="3.1", label="références similaires avec attestations bonne fin",
                         max_points=20, estimated_score=18, risk_level="FAIBLE", rationale="3 PV en GED"),
    ])
    ex = _ex("Fournir trois références similaires avec attestations de bonne fin")
    statut, just, conf, preuve = derive_suggested_status(ex, sc)
    assert statut == STATUT_CONFORME
    assert "3.1" in preuve or "références" in preuve.lower()
    assert 0.0 < conf <= 1.0


def test_critere_basse_note_est_non_conforme():
    sc = _scoring(criteria_breakdown=[
        ScoringCriterion(id="4.2", label="livrables analytics business intelligence",
                         max_points=20, estimated_score=3, risk_level="ÉLEVÉ", rationale="pas de réf BI"),
    ])
    ex = _ex("Démontrer des livrables analytics et business intelligence")
    statut, *_ = derive_suggested_status(ex, sc)
    assert statut == STATUT_NON_CONFORME


def test_risque_bloquant_rend_non_conforme():
    sc = _scoring(risks=[Risk(label="absence de certification ISO 27001",
                              criticite="CRITIQUE", pourquoi="exigée et non détenue")])
    ex = _ex("Disposer de la certification ISO 27001 en cours de validité")
    statut, *_ = derive_suggested_status(ex, sc)
    assert statut == STATUT_NON_CONFORME


def test_force_rend_conforme():
    sc = _scoring(strengths=["Forte expérience en déploiement Odoo multi-sociétés"])
    ex = _ex("Expérience avérée en déploiement Odoo")
    statut, *_ = derive_suggested_status(ex, sc)
    assert statut == STATUT_CONFORME


def test_profil_avec_cv_partiel_sans_cv_a_traiter():
    cv = MatchedDocument(doc_id="1", filename="CV_Dev.pdf", doc_type="cv",
                         relevance_score=0.8, excerpt="...")
    ex = _ex("Ingénieur développeur senior", type_=TYPE_PROFIL)
    statut_with, *_ = derive_suggested_status(ex, _scoring(team_matches=[cv]))
    statut_without, *_ = derive_suggested_status(ex, _scoring(team_matches=[]))
    assert statut_with == STATUT_CONFORME_PARTIEL
    assert statut_without == STATUT_A_TRAITER


def test_seuil_eliminatoire_reste_a_traiter():
    ex = _ex("Chiffre d'affaires annuel minimum 500 millions FCFA", type_=TYPE_SEUIL, blocking=True)
    statut, just, *_ = derive_suggested_status(ex, _scoring())
    assert statut == STATUT_A_TRAITER
    assert "manuel" in just.lower() or "vérifie" in just.lower() or "réunir" in just.lower()


def test_assess_matrice_remplit_suggere_sans_toucher_humain():
    sc = _scoring(strengths=["Expertise Odoo confirmée"])
    matrice = MatriceConformite(ao_filename="ao.pdf", exigences=[
        Exigence(id="EX-0001", texte="Expertise Odoo", type=TYPE_CRITERE),
    ])
    assess_matrice(matrice, sc)
    ex = matrice.exigences[0]
    assert ex.statut_suggere == STATUT_CONFORME
    assert ex.justification_ia
    # Le statut HUMAIN n'est jamais posé par l'IA : il reste « à traiter ».
    assert ex.statut_conformite == STATUT_A_TRAITER
    assert ex.confirme is False


def test_exigence_roundtrip_retrocompatible():
    # Un ancien dict sans les nouveaux champs doit se recharger sans casse.
    old = {"id": "EX-0009", "texte": "vieille exigence", "type": "BESOIN",
           "statut_conformite": "CONFORME"}
    ex = Exigence.from_dict(old)
    assert ex.statut_suggere == STATUT_A_TRAITER  # défaut
    assert ex.confirme is False
    # to_dict expose désormais les nouveaux champs.
    d = ex.to_dict()
    for k in ("statut_suggere", "justification_ia", "confiance_ia", "confirme", "confirme_par"):
        assert k in d
