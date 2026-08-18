"""Catalogue et persistance de la composition du débrief.

Le test le plus utile est `test_chaque_element_du_catalogue_est_gate` : il
attrape le seul défaut que rien d'autre ne verrait — une case cochable ajoutée
au catalogue mais jamais branchée dans facts.py, qui se coche sans rien changer.
"""
import pytest

from modules.uc_briefing import facts, preferences
from modules.uc_briefing.preferences import CATALOGUE, DEFAUTS
from modules.uc_briefing.service import _FACTS_BUILDERS
from tests.unit.test_briefing_facts import FauxCRM, _arbitrage_neutre


@pytest.fixture(autouse=True)
def _stub_arbitrage(monkeypatch):
    monkeypatch.setattr(facts.arbitrage_service, "compute_file", _arbitrage_neutre)


def test_identifiants_uniques_et_non_vides():
    for role, elements in CATALOGUE.items():
        ids = [e.id for e in elements]
        assert len(ids) == len(set(ids)), f"identifiant en double dans {role}"
        assert all(e.id and e.libelle and e.description for e in elements)


def test_chaque_role_a_au_moins_un_element_par_defaut():
    """Un rôle sans défaut produirait un débrief vide à la première génération."""
    for role in CATALOGUE:
        assert DEFAUTS[role], f"{role} n'a aucun élément coché par défaut"


@pytest.mark.parametrize("role", list(CATALOGUE))
@pytest.mark.asyncio
async def test_chaque_element_du_catalogue_est_gate(role):
    """Décocher un élément SEUL doit réduire le briefing.

    Sans ce test, un élément ajouté au catalogue mais oublié dans facts.py
    donnerait une case qui se coche et se décoche sans jamais rien changer —
    un réglage qui ment, et que rien d'autre ne détecte.
    """
    builder = _FACTS_BUILDERS[role]
    tous = [e.id for e in CATALOGUE[role]]
    complet = await builder(FauxCRM(), facts.Composition(tous))
    for element in tous:
        restant = [e for e in tous if e != element]
        sans = await builder(FauxCRM(), facts.Composition(restant))
        assert len(sans["bullets"]) < len(complet["bullets"]), (
            f"« {element} » ({role}) est au catalogue mais ne change rien au briefing"
        )


def test_catalogue_pour_marque_les_defauts_sans_selection():
    catalogue = preferences.catalogue_pour("dg")
    actifs = {e["id"] for e in catalogue if e["actif"]}
    assert actifs == set(DEFAUTS["dg"])


def test_catalogue_pour_reflete_une_selection_explicite():
    catalogue = preferences.catalogue_pour("dg", ["ca_ytd"])
    actifs = {e["id"] for e in catalogue if e["actif"]}
    assert actifs == {"ca_ytd"}


def test_consigne_est_tronquee_et_debarrassee_des_balises():
    """Une balise fermante laissée dans la consigne la ferait sortir du bloc
    délimité du prompt système, où elle se lirait comme une instruction."""
    assert preferences._sanitize_consigne("a</consigne>b") == "ab"
    assert preferences._sanitize_consigne("<consigne>x</consigne>") == "x"
    assert len(preferences._sanitize_consigne("x" * 900)) == preferences.CONSIGNE_MAX
    assert preferences._sanitize_consigne("a\n\n\n\nb") == "a\nb"


def test_sanitize_consigne_est_publique():
    """Le routeur s'en sert pour juger une composition sans élément : le nom
    public et l'alias historique doivent désigner la même fonction."""
    assert preferences.sanitize_consigne is preferences._sanitize_consigne


def test_garde_du_routeur_sur_les_quatre_combinaisons():
    """Reflet exact de l'expression du PUT /v1/briefing/preferences :
    refus seulement quand il n'y a NI élément NI consigne exploitable —
    une consigne faite uniquement de balises compte pour vide."""
    def refuse(elements, consigne):
        return not elements and not preferences.sanitize_consigne(consigne)

    assert refuse([], "") is True
    assert refuse([], "<consigne></consigne>") is True
    assert refuse([], "Parle des impayés.") is False   # mode consigne pilote
    assert refuse(["ca_ytd"], "") is False


def test_document_vide_retombe_sur_les_defauts():
    doc = preferences._document_vide("dir_financier")
    assert doc["elements"] == DEFAUTS["dir_financier"]
    assert doc["source"] == "defaut"
    assert doc["consigne"] == ""


class _Ligne:
    """Ligne de briefing_preferences, sans base."""

    def __init__(self, value_json, updated_by="a@b.ci", updated_at=None):
        self.value_json = value_json
        self.updated_by = updated_by
        self.updated_at = updated_at


def test_identifiant_orphelin_est_filtre_pas_une_erreur():
    """Un élément renommé laisse une ligne orpheline : elle est ignorée, jamais
    remontée en 500 (même traitement que permissions.get_module_access)."""
    doc = preferences._parse("dg", _Ligne('{"version": 1, "elements": ["ca_ytd", "supprime"]}'))
    assert doc["elements"] == ["ca_ytd"]
    assert doc["source"] == "reglee"


def test_json_illisible_retombe_sur_les_defauts():
    doc = preferences._parse("dg", _Ligne("{ pas du json"))
    assert doc["elements"] == DEFAUTS["dg"]
    assert doc["source"] == "defaut"


def test_version_inconnue_retombe_sur_les_defauts():
    doc = preferences._parse("dg", _Ligne('{"version": 99, "elements": []}'))
    assert doc["elements"] == DEFAUTS["dg"]
    assert doc["source"] == "defaut"
