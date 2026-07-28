"""Tests de la consolidation ScoringResult → MatriceConformite (C3).

Cœur : la garantie d'EXHAUSTIVITÉ (aucune exigence perdue) + la règle de
dédoublonnage profils/ressources + la propagation source_ref/blocking + la
classification par domaine. Aucun appel LLM."""
from core.domain.offer import (
    ScoringResult, ExtractedItem, RequiredProfile, EligibilityThreshold, Appendix,
    BidRecommendation,
)
from core.domain.requirements import (
    TYPE_PROFIL, TYPE_RESSOURCE, TYPE_SEUIL, TYPE_ANNEXE, DOMAINE_NON_CLASSE,
)
from modules.uc10_presales.requirements_builder import build_matrice


def _scoring(**over) -> ScoringResult:
    base = dict(
        ao_filename="AO.pdf", summary="", key_elements=[], matched_documents=[],
        gaps_analysis="", strengths=[], risks=[], score=60,
        recommendation=BidRecommendation.GO, justification="",
    )
    base.update(over)
    return ScoringResult(**base)


def _items(*textes) -> list[ExtractedItem]:
    return [ExtractedItem(texte=t) for t in textes]


def test_exhaustivity_no_profils_counts_ressources():
    scoring = _scoring(
        besoins=_items("b1", "b2"),
        criteres_selection=_items("c1", "c2"),
        prerequis=_items("p1"),
        ressources_demandees=_items("r1", "r2"),
        points_vigilance=_items("v1"),
        seuils_eligibilite=[EligibilityThreshold(libelle="CA min", valeur="500M")],
        appendices=[Appendix(code="5A", label="Déclaration")],
    )
    m = build_matrice(scoring)
    # 2+2+1+2+1+1+1 = 10 — rien perdu
    assert m.total == 10
    assert m.expected_total == 10
    assert m.is_exhaustive is True


def test_profils_present_skips_ressources():
    scoring = _scoring(
        besoins=_items("b1"),
        ressources_demandees=_items("r1", "r2", "r3"),  # doivent être ignorées
        profils_demandes=[
            RequiredProfile(profil="Ingénieur Data", quantite=2, niveau="BAC+5"),
            RequiredProfile(profil="Analyste SOC"),
        ],
    )
    m = build_matrice(scoring)
    # 1 besoin + 2 profils, ressources ignorées
    assert m.total == 3
    types = {e.type for e in m.exigences}
    assert TYPE_PROFIL in types
    assert TYPE_RESSOURCE not in types


def test_source_ref_and_blocking_propagation():
    scoring = _scoring(
        besoins=[ExtractedItem(texte="Virtualisation", source_section="§4.1")],
        seuils_eligibilite=[EligibilityThreshold(libelle="CA", valeur="500M", blocking=True, source_section="Art.7")],
        appendices=[Appendix(code="A1", label="Caution", obligatoire=False, source_section="§9")],
    )
    m = build_matrice(scoring)
    by_type = {e.type: e for e in m.exigences}
    assert by_type["BESOIN"].source_ref == "§4.1"
    assert by_type[TYPE_SEUIL].blocking is True
    assert by_type[TYPE_SEUIL].source_ref == "Art.7"
    assert by_type[TYPE_ANNEXE].blocking is False  # facultatif → non bloquant


def test_classification_runs_per_exigence():
    scoring = _scoring(besoins=_items("Hébergement cloud AWS et Azure", "Prestation de gardiennage"))
    m = build_matrice(scoring)
    cloud = next(e for e in m.exigences if "cloud" in e.texte.lower())
    other = next(e for e in m.exigences if "gardiennage" in e.texte.lower())
    assert "Cloud" in cloud.domaines_suggeres
    assert other.domaines_suggeres == [DOMAINE_NON_CLASSE]


def test_empty_texts_are_dropped():
    scoring = _scoring(besoins=[ExtractedItem(texte=""), ExtractedItem(texte="  "), ExtractedItem(texte="ok")])
    m = build_matrice(scoring)
    assert m.total == 1
    assert m.exigences[0].texte == "ok"


def test_ids_are_stable_and_sequential():
    scoring = _scoring(besoins=_items("a", "b", "c"))
    m = build_matrice(scoring)
    assert [e.id for e in m.exigences] == ["EX-0001", "EX-0002", "EX-0003"]
