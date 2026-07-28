"""Tests de normalisation des libellés d'entités (Phase 2)."""
from core.services.entity_resolution.normalize import normalize


def test_client_retire_forme_juridique():
    assert normalize("SGBCI SA", "client") == "sgbci"
    assert normalize("Orange CI SARL", "client") == "orange ci"


def test_accents_ponctuation_casse():
    assert normalize("Société Générale", "client") == "societe generale"
    assert normalize("S.G.B.C.I.", "client") == "sgbci"
    assert normalize("Réunion d'Équipe", "projet") == "reunion d equipe"


def test_personne_inchangee_hors_normalisation():
    assert normalize("Jean Kouassi", "personne") == "jean kouassi"


def test_label_vide():
    assert normalize(None, "client") == ""
    assert normalize("   ", "projet") == ""
