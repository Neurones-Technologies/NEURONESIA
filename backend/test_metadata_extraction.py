"""Smoke test des nouveaux parsers (MarketIdentity, Calendar, EvaluationModalities)
et du round-trip Pydantic ScoringResult <-> ScoringResultSchema.

Aucun appel LLM — on vérifie juste que le code domaine + schemas + pipeline
s'assemble correctement et résiste aux JSON malformés/partiels.
"""
import json
from core.domain.offer import (
    ScoringResult, MarketIdentity, CalendarEvent, EvaluationModalities,
    KeyElement, BidRecommendation, Risk, ExtractedItem,
)
from modules.uc10_presales.scoring_pipeline import ScoringPipeline
from modules.uc10_presales.schemas import ScoringResultSchema
from modules.uc10_presales.router import _to_schema, _from_schema


def test_parsers():
    print("=" * 60)
    print("1. Parsers — cas nominal (JSON complet du LLM)")
    print("=" * 60)
    raw = {
        "market_identity": {
            "type_marche": "Marché public de prestation",
            "reference": "ADB/RFP/TCGS/2026/0104",
            "autorite_contractante": "Banque Africaine de Développement",
            "duree_contrat": "1 an + 2 renouvellements",
            "date_demarrage": "01/06/2026",
            "deadline_soumission": "15/06/2026 17:00 GMT",
            "validite_offre": "120 jours",
            "perimetre_geographique": "Côte d'Ivoire",
            "eligibilite_candidat": "Sociétés enregistrées en CI",
            "confidence": 0.85,
        },
        "calendar": [
            {"label": "Limite questions", "date": "05/06/2026", "criticite": "CRITIQUE", "source_section": "§XVII"},
            {"label": "Remise offres", "date": "15/06/2026 17:00", "criticite": "BLOQUANT", "source_section": "§XVII"},
        ],
        "evaluation_modalities": {
            "ponderation_technique": 70,
            "ponderation_financiere": 30,
            "seuil_minimum_technique": 70,
            "formule_notation_financiere": "Nf = 100 × Fm / F",
            "modalites": ["Démo orale", "POC requis"],
            "confidence": 0.9,
        },
    }
    identity = ScoringPipeline._parse_market_identity(raw["market_identity"])
    calendar = ScoringPipeline._parse_calendar(raw["calendar"])
    evaluation = ScoringPipeline._parse_evaluation(raw["evaluation_modalities"])

    assert identity.reference == "ADB/RFP/TCGS/2026/0104"
    assert identity.confidence == 0.85
    assert len(calendar) == 2
    assert calendar[0].criticite == "CRITIQUE"
    assert calendar[1].criticite == "BLOQUANT"
    assert evaluation.ponderation_technique == 70
    assert evaluation.ponderation_financiere == 30
    assert evaluation.confidence == 0.9
    print("  OK : tous les champs extraits correctement")

    print("\n" + "=" * 60)
    print("2. Parsers — cas vide (LLM n'a rien trouvé)")
    print("=" * 60)
    identity2 = ScoringPipeline._parse_market_identity(None)
    calendar2 = ScoringPipeline._parse_calendar(None)
    evaluation2 = ScoringPipeline._parse_evaluation(None)
    assert identity2.confidence == 0.0
    assert identity2.reference == ""
    assert calendar2 == []
    assert evaluation2.ponderation_technique == 0
    assert evaluation2.confidence == 0.0
    print("  OK : retour à des dataclasses vides + confidence=0")

    print("\n" + "=" * 60)
    print("2b. Confidence dérivée — bug observé sur NEEMBA (LLM disait 0.7, valeurs à 0/0)")
    print("=" * 60)
    # LLM annonce confidence haute mais les pondérations sont à 0/0 → derived doit l'écraser
    bug_neemba = {
        "ponderation_technique": 0,
        "ponderation_financiere": 0,
        "seuil_minimum_technique": 0,
        "formule_notation_financiere": "",
        "modalites": [],
        "confidence": 0.7,
    }
    eval_neemba = ScoringPipeline._parse_evaluation(bug_neemba)
    assert eval_neemba.confidence <= 0.1, f"Expected <=0.1, got {eval_neemba.confidence}"
    print(f"  OK : LLM=0.7 -> dérivée={eval_neemba.confidence} (effondrement car pondérations=0/0)")

    # MarketIdentity quasi vide mais LLM annonce 0.8
    bug_identity = {
        "reference": "TBF-06-2026",   # 1 champ critique seulement
        "deadline_soumission": "",
        "autorite_contractante": "",
        "type_marche": "",
        "duree_contrat": "",
        "date_demarrage": "",
        "validite_offre": "",
        "perimetre_geographique": "",
        "eligibilite_candidat": "",
        "confidence": 0.8,
    }
    id_neemba = ScoringPipeline._parse_market_identity(bug_identity)
    # 1 critique * 2 / 12 = 0.166...
    assert id_neemba.confidence <= 0.2, f"Expected <=0.2, got {id_neemba.confidence}"
    print(f"  OK : LLM=0.8 -> dérivée={id_neemba.confidence} (1 champ critique sur 3 + 0 autres)")

    # Cas symétrique : LLM honnête (0.3), tous les champs critiques remplis -> on garde 0.3
    honest = {
        "reference": "X", "deadline_soumission": "Y", "autorite_contractante": "Z",
        "type_marche": "", "duree_contrat": "", "date_demarrage": "",
        "validite_offre": "", "perimetre_geographique": "", "eligibilite_candidat": "",
        "confidence": 0.3,
    }
    id_honest = ScoringPipeline._parse_market_identity(honest)
    # 3 critiques * 2 / 12 = 0.5 ; min(0.3, 0.5) = 0.3
    assert id_honest.confidence == 0.3, f"Expected 0.3, got {id_honest.confidence}"
    print(f"  OK : LLM=0.3 + 3/3 critiques -> {id_honest.confidence} (LLM respecté car sous-évalue)")

    print("\n" + "=" * 60)
    print("3. Parsers — cas malformé (criticité bidon, confidence string, ponderation negative)")
    print("=" * 60)
    bad = {
        "market_identity": {"confidence": "haute"},   # string au lieu de float
        "calendar": [
            {"label": "x", "date": "01/01/2026", "criticite": "MEGA-URGENT"},  # criticité invalide
            {"label": "", "date": "01/01/2026"},   # label vide -> skip
            "not_a_dict",                          # type invalide -> skip
        ],
        "evaluation_modalities": {"ponderation_technique": -5, "ponderation_financiere": 200},
    }
    identity3 = ScoringPipeline._parse_market_identity(bad["market_identity"])
    calendar3 = ScoringPipeline._parse_calendar(bad["calendar"])
    evaluation3 = ScoringPipeline._parse_evaluation(bad["evaluation_modalities"])
    assert identity3.confidence == 0.0   # string -> fallback 0
    assert len(calendar3) == 1            # malformés filtrés
    assert calendar3[0].criticite == "INFO"  # criticité bidon -> INFO
    assert evaluation3.ponderation_technique == 0    # negatif -> clamp à 0
    assert evaluation3.ponderation_financiere == 100  # >100 -> clamp à 100
    print("  OK : tous les inputs invalides absorbés sans crash")


def test_round_trip():
    print("\n" + "=" * 60)
    print("4. Round-trip ScoringResult <-> ScoringResultSchema")
    print("=" * 60)
    original = ScoringResult(
        ao_filename="test.pdf",
        summary="Test summary",
        key_elements=[KeyElement(category="Budget", value="100M FCFA")],
        matched_documents=[],
        gaps_analysis="",
        strengths=["Force 1"],
        risks=[Risk(label="Risque 1")],
        score=75,
        recommendation=BidRecommendation.GO,
        justification="Justification test",
        criteres_selection=[ExtractedItem(texte="Critère X")],
        besoins=[ExtractedItem(texte="Besoin Y", source_section="§3")],
        prerequis=[],
        ressources_demandees=[],
        points_vigilance=[],
        date_remise="15/06/2026",
        market_identity=MarketIdentity(
            reference="ADB/RFP/2026/0104",
            deadline_soumission="15/06/2026 17:00",
            confidence=0.85,
        ),
        calendar=[
            CalendarEvent(label="Remise", date="15/06/2026", criticite="BLOQUANT"),
        ],
        evaluation_modalities=EvaluationModalities(
            ponderation_technique=70,
            ponderation_financiere=30,
            confidence=0.9,
        ),
    )

    schema = _to_schema(original)
    print(f"  -> schema.market_identity.reference = '{schema.market_identity.reference}'")
    print(f"  -> schema.calendar[0].criticite = '{schema.calendar[0].criticite}'")
    print(f"  -> schema.evaluation_modalities.ponderation_technique = {schema.evaluation_modalities.ponderation_technique}")

    # Sérialisation JSON (ce qui passe sur l'API)
    payload = schema.model_dump_json()
    parsed = ScoringResultSchema.model_validate_json(payload)
    print(f"  -> sérialisation JSON: {len(payload)} chars")

    # Retour vers domaine
    restored = _from_schema(parsed)
    assert restored.market_identity.reference == original.market_identity.reference
    assert restored.market_identity.confidence == original.market_identity.confidence
    assert restored.calendar[0].label == original.calendar[0].label
    assert restored.evaluation_modalities.ponderation_technique == 70
    assert restored.date_remise == original.date_remise  # rétrocompat
    # Enrichissement C0 : le texte ET la référence source des exigences survivent au round-trip
    assert restored.besoins[0].texte == "Besoin Y"
    assert restored.besoins[0].source_section == "§3"
    assert restored.risks[0].label == "Risque 1"
    print("  OK : round-trip Domain -> Schema -> JSON -> Schema -> Domain préservé")


def test_backward_compat():
    print("\n" + "=" * 60)
    print("5. Rétrocompat — ScoringResult sans les nouveaux champs")
    print("=" * 60)
    # Comme si on désérialisait un ScoringResult sauvegardé AVANT cette feature
    result = ScoringResult(
        ao_filename="legacy.pdf",
        summary="x",
        key_elements=[],
        matched_documents=[],
        gaps_analysis="",
        strengths=[],
        risks=[],
        score=50,
        recommendation=BidRecommendation.CONDITIONAL,
        justification="x",
    )
    assert result.market_identity.confidence == 0.0
    assert result.calendar == []
    assert result.evaluation_modalities.confidence == 0.0
    print("  OK : ScoringResult ancien (sans nouveaux champs) initialise des défauts vides")

    schema = _to_schema(result)
    assert schema.market_identity.confidence == 0.0
    print("  OK : converti vers schema sans erreur")


if __name__ == "__main__":
    test_parsers()
    test_round_trip()
    test_backward_compat()
    print("\n" + "=" * 60)
    print("TOUS LES TESTS PASSENT")
    print("=" * 60)
