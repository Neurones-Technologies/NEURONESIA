"""Tests du schéma de conformité (core/domain/requirements).

Aucun appel LLM : on vérifie la (dé)sérialisation round-trip, le caractère
multi-valeur du domaine, les statistiques et la normalisation défensive.
"""
from core.domain.requirements import (
    Exigence, MatriceConformite,
    DOMAINE_NON_CLASSE,
    TYPE_BESOIN, TYPE_SEUIL, TYPE_PROFIL,
    STATUT_A_TRAITER, STATUT_CONFORME,
)


def _sample_matrice() -> MatriceConformite:
    return MatriceConformite(
        ao_filename="AO-Test.pdf",
        generated_at="2026-06-22T10:00:00",
        expected_total=3,
        exigences=[
            Exigence(
                id="EX-0001", texte="Développer une application web et mobile",
                source_ref="§3.1", type=TYPE_BESOIN, origine="besoins",
                domaines_suggeres=["Digitalisation", "Cloud"], confidence=0.8,
            ),
            Exigence(
                id="EX-0002", texte="CA annuel minimum 500 000 000 FCFA",
                source_ref="§II.4", type=TYPE_SEUIL, origine="seuils_eligibilite",
                blocking=True, domaines_suggeres=[DOMAINE_NON_CLASSE],
            ),
            Exigence(
                id="EX-0003", texte="1 Analyste Cybersécurité C-SOC, 5 ans",
                source_ref="§5.2", type=TYPE_PROFIL, origine="profils_demandes",
                domaines_suggeres=["Cybersécurité"], domaine_valide="Cybersécurité",
                statut_conformite=STATUT_CONFORME,
            ),
        ],
    )


def test_exigence_round_trip():
    ex = Exigence(
        id="EX-0001", texte="Exigence verbatim", source_ref="§1",
        domaines_suggeres=["Cloud", "Infrastructure"], confidence=0.5,
    )
    again = Exigence.from_dict(ex.to_dict())
    assert again == ex


def test_matrice_json_round_trip():
    m = _sample_matrice()
    again = MatriceConformite.from_json(m.to_json())
    assert again == m
    assert again.total == 3
    assert again.exigences[1].blocking is True


def test_from_dict_ignores_unknown_and_missing_fields():
    ex = Exigence.from_dict({"id": "X", "texte": "T", "champ_inconnu": "ignore"})
    assert ex.id == "X" and ex.texte == "T"
    assert ex.source_ref == ""  # défaut appliqué malgré le champ manquant


def test_domaine_effectif_prefers_validated_then_first_suggested():
    val = Exigence(id="1", texte="t", domaines_suggeres=["Cloud"], domaine_valide="Infrastructure")
    sug = Exigence(id="2", texte="t", domaines_suggeres=["Cloud", "Digitalisation"])
    none = Exigence(id="3", texte="t")
    assert val.domaine_effectif == "Infrastructure"
    assert sug.domaine_effectif == "Cloud"
    assert none.domaine_effectif == DOMAINE_NON_CLASSE


def test_invalid_type_and_statut_are_normalized():
    ex = Exigence(id="1", texte="t", type="FARFELU", statut_conformite="WAT")
    assert ex.type == TYPE_BESOIN
    assert ex.statut_conformite == STATUT_A_TRAITER


def test_count_by_domaine_counts_multivalue_once_per_domain():
    m = _sample_matrice()
    counts = m.count_by_domaine()
    # EX-0001 → Digitalisation + Cloud ; EX-0002 → Non classé ; EX-0003 (validé) → Cybersécurité
    assert counts["Digitalisation"] == 1
    assert counts["Cloud"] == 1
    assert counts[DOMAINE_NON_CLASSE] == 1
    assert counts["Cybersécurité"] == 1


def test_count_by_statut_and_type():
    m = _sample_matrice()
    assert m.count_by_statut()[STATUT_A_TRAITER] == 2
    assert m.count_by_statut()[STATUT_CONFORME] == 1
    assert m.count_by_type()[TYPE_SEUIL] == 1


def test_exhaustivity_flag():
    m = _sample_matrice()
    assert m.is_exhaustive is True
    m.expected_total = 5
    assert m.is_exhaustive is False
    m.expected_total = None
    assert m.is_exhaustive is True
