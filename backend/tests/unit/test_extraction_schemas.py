"""Validation + normalisation des schémas Pydantic d'extraction (Phase 1)."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from core.services.extraction.schemas import ABEExtraction, CVExtraction


def test_cv_normalisation_dates_et_en_cours():
    cv = CVExtraction.model_validate({
        "personne": {"nom_complet": "Jean Kouassi", "annees_experience_total": 12},
        "experiences": [{
            "intitule_projet": "Core banking", "client": "SGBCI", "secteur": "banque",
            "date_debut": "2020-01", "date_fin": "en cours",
        }],
        "certifications_citees": [{"intitule": "PMP", "organisme": "PMI", "annee": "2019"}],
        "champ_inconnu": "ignoré",  # extra="ignore"
    })
    exp = cv.experiences[0]
    assert exp.date_debut == datetime(2020, 1, 1)
    assert exp.date_fin is None
    assert exp.en_cours is True
    assert cv.certifications_citees[0].annee == 2019  # coercition str→int


def test_abe_montant_et_devise_normalises():
    abe = ABEExtraction.model_validate({
        "emetteur_client": "SGBCI",
        "projet_marche": "Refonte SI",
        "montant": {"valeur": "250 000 000 FCFA", "devise": "FCFA"},
        "date_fin": "30/06/2024",
    })
    assert abe.montant.valeur == 250_000_000.0
    assert abe.montant.devise == "XOF"            # FCFA canonicalisé
    assert abe.date_fin == datetime(2024, 6, 30)


def test_abe_montant_nombre_simple():
    abe = ABEExtraction.model_validate({
        "emetteur_client": "X", "projet_marche": "Y",
        "montant": {"valeur": 250000000, "devise": "EUR"},
    })
    assert abe.montant.valeur == 250_000_000.0
    assert abe.montant.devise == "EUR"


def test_validation_echoue_sur_type_incoercible():
    with pytest.raises(ValidationError):
        CVExtraction.model_validate({
            "personne": {"annees_experience_total": "douze"},  # non convertible en float
        })
