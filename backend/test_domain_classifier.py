"""Tests du classifieur de domaine (modules/uc10_presales/domain_classifier).

On vérifie : scoring, multi-domaine, repli « Non classé », insensibilité aux
accents, et l'anti-faux-positif par frontière de mot (le point faible du
matching par sous-chaîne d'origine)."""
from modules.uc10_presales.domain_classifier import (
    classify, suggested_domains, primary_domain, DEFAULT_DOMAIN,
)
from core.domain.requirements import DOMAINE_NON_CLASSE


def test_single_domain():
    scores = classify("Développement d'une application web et mobile")
    assert scores[0].domaine == "Digitalisation"
    assert primary_domain("Développement d'une application web") == "Digitalisation"


def test_multi_domaine_ranked_by_score():
    text = ("Application web hébergée sur le cloud AWS et Azure, "
            "avec firewall, SIEM et SOC pour la cybersécurité")
    domaines, conf = suggested_domains(text)
    assert "Cloud" in domaines
    assert "Cybersécurité" in domaines
    assert "Digitalisation" in domaines
    assert 0.0 < conf <= 1.0
    assert len(domaines) <= 3  # plafonné


def test_no_match_falls_back():
    domaines, conf = suggested_domains("Prestation de nettoyage des locaux")
    assert domaines == [DOMAINE_NON_CLASSE]
    assert conf == 0.0
    # la vue mono-domaine retombe sur le défaut, jamais sur « Non classé »
    assert primary_domain("Prestation de nettoyage des locaux") == DEFAULT_DOMAIN


def test_accent_insensitive():
    # texte sans accents → doit matcher les mots-clés accentués
    assert primary_domain("audit de cybersecurite et chiffrement") == "Cybersécurité"


def test_word_boundary_avoids_substring_false_positives():
    # « rapide » contient la sous-chaîne « api », « société » contient « soc » :
    # le matching sur frontière de mot ne doit PAS les compter.
    assert classify("Une réponse rapide de la société") == []


def test_multiword_keyword_matches_as_phrase():
    scores = classify("Hébergement en data center régional")
    domaines = {s.domaine for s in scores}
    assert "Infrastructure" in domaines  # "data center"
    assert "Cloud" in domaines           # "hébergement"


def test_confidence_is_relative_share():
    # 1 hit Cloud seul → confiance primaire = 1.0 (100% des hits)
    _, conf = suggested_domains("migration cloud")
    assert conf == 1.0
