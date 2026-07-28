"""Tests de l'enrichissement des exigences (C0) : besoins/critères/prérequis/
ressources/vigilance portent désormais {texte, source_section}.

On vérifie la coercion bidirectionnelle (domaine ↔ schéma) et la compatibilité
ascendante : un ancien cache/payload `list[str]` reste lisible (coercion vers
{texte, source_section:""}), aucune perte ni exception. Aucun appel LLM."""
from core.domain.offer import ExtractedItem
from modules.uc10_presales.schemas import ExtractedItemSchema, ScoringResultSchema
from modules.uc10_presales.router import _to_schema, _from_schema


def test_extracted_item_coerce_from_str_dict_obj():
    assert ExtractedItem.coerce("Besoin X") == ExtractedItem(texte="Besoin X")
    assert ExtractedItem.coerce({"texte": "B", "source_section": "§3"}) == ExtractedItem("B", "§3")
    # objet portant .texte (ex: schéma Pydantic)
    sch = ExtractedItemSchema(texte="C", source_section="§4")
    assert ExtractedItem.coerce(sch) == ExtractedItem("C", "§4")
    # repli robuste
    assert ExtractedItem.coerce(123).texte == "123"


def test_schema_coerces_legacy_string_shape():
    """Ancien cache : besoins = ["str"] → ExtractedItemSchema{texte:"str"}."""
    s = ScoringResultSchema(
        ao_filename="a.pdf", summary="", key_elements=[], matched_documents=[],
        gaps_analysis="", strengths=[], risks=[], score=50,
        recommendation="GO", justification="",
        besoins=["Besoin hérité"],  # ancien format string
        criteres_selection=[{"texte": "Critère", "source_section": "§2"}],  # nouveau format
    )
    assert s.besoins[0].texte == "Besoin hérité"
    assert s.besoins[0].source_section == ""
    assert s.criteres_selection[0].source_section == "§2"


def _minimal_schema(**over) -> ScoringResultSchema:
    base = dict(
        ao_filename="ao.pdf", summary="", key_elements=[], matched_documents=[],
        gaps_analysis="", strengths=[], risks=[], score=60,
        recommendation="GO", justification="",
    )
    base.update(over)
    return ScoringResultSchema(**base)


def test_router_round_trip_preserves_source_ref():
    schema = _minimal_schema(
        besoins=[{"texte": "Virtualisation 50 serveurs", "source_section": "§4.1"}],
        prerequis=[{"texte": "Présence locale CI", "source_section": "Art. 7"}],
        points_vigilance=[{"texte": "Pénalité 0.5%/sem", "source_section": ""}],
    )
    # schéma → domaine → schéma : texte ET source_section survivent
    domain = _from_schema(schema)
    assert domain.besoins[0].texte == "Virtualisation 50 serveurs"
    assert domain.besoins[0].source_section == "§4.1"
    assert domain.prerequis[0].source_section == "Art. 7"

    back = _to_schema(domain)
    assert back.besoins[0].texte == "Virtualisation 50 serveurs"
    assert back.besoins[0].source_section == "§4.1"
    # sérialisation JSON (comme le cache disque) conserve la forme objet
    dumped = back.model_dump(mode="json")
    assert dumped["besoins"][0] == {"texte": "Virtualisation 50 serveurs", "source_section": "§4.1"}


def test_from_schema_handles_legacy_cache_then_to_schema():
    """Bout en bout : ancien cache (str) → domaine → schéma, sans perte ni crash."""
    legacy = _minimal_schema(besoins=["Ancien besoin"], ressources_demandees=["Chef de projet"])
    domain = _from_schema(legacy)
    assert domain.besoins[0].texte == "Ancien besoin"
    assert domain.ressources_demandees[0].texte == "Chef de projet"
    assert _to_schema(domain).besoins[0].texte == "Ancien besoin"
