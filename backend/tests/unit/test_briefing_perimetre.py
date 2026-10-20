"""Briefings sous périmètre pays (profils hors DG) : construits sur les seules
données du pays, sans variation comparée à l'historique du groupe, et sans les
éléments dont les sources n'ont pas de pays — nommés plutôt que tus.
"""
import pytest

from core.services import perimetre
from modules.uc_briefing import analyses, facts, indicateurs, service, store


@pytest.mark.asyncio
async def test_le_builder_tourne_sous_le_perimetre_et_perd_les_sources_sans_pays(monkeypatch):
    vus = {}

    async def builder(crm, composition):
        vus["entite"] = perimetre.entite_courante()
        vus["mouvements"] = composition.actif("mouvements_recents")
        vus["pipeline"] = composition.actif("pipeline_ouvert")
        return {"facts": {}, "bullets": ["Pipeline ouvert : …"], "blocs": {"chiffre": ["…"]},
                "action": None, "cadence": "CA commandé : … ▲ vs hier"}

    monkeypatch.setitem(service._FACTS_BUILDERS, "dir_commercial", builder)
    built = await facts.build_facts_entite("dir_commercial", object(), None, "BF")

    assert vus == {"entite": "BF", "mouvements": False, "pipeline": True}
    assert perimetre.entite_courante() is None                     # périmètre rendu après coup
    assert built["facts"] == {"entite": "BF", "elements_groupe_seulement": ["mouvements_recents"]}
    assert built["bullets"][-1].startswith("Périmètre Burkina Faso")
    assert built["cadence"] == ""                                   # pas de mouvement vs groupe


def test_sources_sans_pays_par_role():
    assert facts.elements_sans_pays("dir_financier") == {"echeancier_fournisseurs"}
    assert facts.elements_sans_pays("dir_operations") == {"fiabilite_fournisseurs", "risque_rupture_fournisseur"}
    assert "mouvements_recents" in facts.elements_sans_pays("commercial")


@pytest.mark.asyncio
async def test_sous_perimetre_les_indicateurs_servent_la_valeur_du_jour_seule(monkeypatch):
    async def delta(*a, **k):
        raise AssertionError("l'historique groupe ne doit pas être lu sous un périmètre pays")

    async def calculer(cle, jour, historique=None):
        return 42.0
    monkeypatch.setattr(indicateurs, "delta", delta)
    monkeypatch.setattr(indicateurs, "calculer", calculer)
    jeton = perimetre.definir("CI")
    try:
        blocs = await facts._deltas(["ca_facture_mois", "dette_fournisseurs_echue"])
    finally:
        perimetre.reinitialiser(jeton)
    assert set(blocs) == {"ca_facture_mois"}                       # dette fournisseurs : sans pays
    assert blocs["ca_facture_mois"]["valeur"] == 42.0 and "j1" not in blocs["ca_facture_mois"]


@pytest.mark.asyncio
async def test_objectifs_de_lentite_sous_perimetre(monkeypatch):
    params = []

    async def _lignes(sql, p):
        params.append(p)
        return [(0, 0, 0)]
    monkeypatch.setattr(analyses, "_lignes", _lignes)
    jeton = perimetre.definir("BF")
    try:
        await analyses.objectifs_annuels(2026)
    finally:
        perimetre.reinitialiser(jeton)
    assert all(p.get("e") == "BF" for p in params if "e" in p) and any("e" in p for p in params)


@pytest.mark.asyncio
async def test_visibilite_absurde_non_convertie(monkeypatch):
    reponses = iter([[(900_000.0, 2)], [(11.9e9,)]])            # facturé 3 mois, puis backlog

    async def _lignes(sql, p):
        return next(reponses)
    monkeypatch.setattr(analyses, "_lignes", _lignes)
    v = await analyses.visibilite_carnet()
    assert v["mesurable"] is False and "trop faible" in v["raison"]


@pytest.fixture
def store_temporaire(tmp_path, monkeypatch):
    vrai_save, vrai_load = store.save, store.load
    monkeypatch.setattr(store, "save", lambda payload, base=None: vrai_save(payload, base=tmp_path))
    monkeypatch.setattr(store, "load", lambda base=None: vrai_load(base=tmp_path))

    async def _load(role):
        return None

    async def _charger(role):
        return {}
    monkeypatch.setattr(service.preferences, "load", _load)
    monkeypatch.setattr(service.seuils_mod, "charger", _charger)
    return lambda: vrai_load(base=tmp_path)


@pytest.mark.asyncio
async def test_section_dentite_generee_a_la_demande_pour_un_profil_hors_dg(store_temporaire, monkeypatch):
    async def faits(role, crm, composition, entite):
        return {"facts": {"entite": entite}, "bullets": [f"{role}@{entite}"], "action": None, "cadence": ""}
    monkeypatch.setattr(facts, "build_facts_entite", faits)
    store.save({"generated_at": None, "triggered_by": None, "sections": {}, "sections_en_echec": []})

    section = await service.generate_entite("dir_financier", "BF", object(), None)
    assert section["facts"]["entite"] == "BF"
    assert "dir_financier@BF" in store_temporaire()["sections"]


@pytest.mark.asyncio
async def test_relance_dun_profil_hors_dg_perime_ses_sections_dentite(store_temporaire, monkeypatch):
    async def builder(crm, composition):
        return {"facts": {}, "bullets": ["…"], "action": None, "cadence": ""}
    monkeypatch.setitem(service._FACTS_BUILDERS, "dir_financier", builder)
    store.save({"generated_at": None, "triggered_by": None, "sections_en_echec": [],
                "sections": {"dir_financier@BF": {"facts": {}}, "dg@BF": {"facts": {}}}})

    await service.generate_role("dir_financier", object(), None)
    sections = store_temporaire()["sections"]
    assert "dir_financier@BF" not in sections                       # refaite au prochain affichage
    assert "dg@BF" in sections and "dir_financier" in sections
