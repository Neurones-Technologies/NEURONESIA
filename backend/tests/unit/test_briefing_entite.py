"""Briefing DG d'une entité (sélecteur « Pays » du cockpit DG).

Ce qui ne doit jamais arriver : un chiffre groupe dans un briefing pays (il se
lirait comme un chiffre du pays), ou un sujet retiré sans le dire (le DG
croirait qu'il n'y a rien à signaler sur les impayés du pays).
"""
import pytest

from modules.uc_briefing import facts, service, store


class CRMEntite:
    """Répond à tout, et note l'entité demandée à chaque source."""

    def __init__(self):
        self.appels: list[tuple[str, str | None]] = []

    def __getattr__(self, nom):
        async def source(*args, entite=None, **kwargs):
            self.appels.append((nom, entite))
            if nom in ("get_ytd_stats", "get_year_stats"):
                return {"revenue_xof": 5e9 if entite else 8e9, "orders_count": 10,
                        "clients_with_orders": 5, "as_of": "2026-10-19"}
            raise RuntimeError("source sans données dans ce test")
        return source


@pytest.mark.asyncio
async def test_briefing_entite_ne_lit_que_des_sources_filtrees(monkeypatch):
    async def _deltas(cles, arret=None):
        raise AssertionError("aucune variation groupe dans un briefing d'entité")
    monkeypatch.setattr(facts, "_deltas", _deltas)
    crm = CRMEntite()
    b = await facts.build_dg_facts(crm, entite="CI")
    sources = {nom for nom, _ in crm.appels}
    assert all(e == "CI" for _, e in crm.appels), crm.appels           # toutes filtrées
    assert "get_unpaid_exposure" not in sources and "get_margin_stats" not in sources
    assert b["facts"]["entite"] == "CI" and b["facts"]["ca_ytd_xof"] == 5e9
    assert b["cadence"] == ""                                           # pas de « vs hier » groupe


@pytest.mark.asyncio
async def test_briefing_entite_nomme_ce_quil_ne_porte_pas():
    b = await facts.build_dg_facts(CRMEntite(), entite="BF")
    perimetre = [p for p in b["bullets"] if p.startswith("Périmètre Burkina Faso")]
    assert perimetre and "position nette de trésorerie" in perimetre[0].lower()
    assert "position_tresorerie" in b["facts"]["elements_groupe_seulement"]
    assert "ca_ytd" not in b["facts"]["elements_groupe_seulement"]


@pytest.mark.asyncio
async def test_briefing_groupe_inchange():
    crm = CRMEntite()
    b = await facts.build_dg_facts(crm)
    assert all(e is None for _, e in crm.appels)
    assert "entite" not in b["facts"] and not any(p.startswith("Périmètre") for p in b["bullets"])


@pytest.mark.asyncio
async def test_generate_produit_les_sections_dentite(tmp_path, monkeypatch):
    vrai_save, vrai_load = store.save, store.load
    monkeypatch.setattr(store, "save", lambda payload, base=None: vrai_save(payload, base=tmp_path))
    monkeypatch.setattr(store, "load", lambda base=None: vrai_load(base=tmp_path))

    async def _load_all():
        return {}

    async def _seuils():
        return {}
    monkeypatch.setattr(service.preferences, "load_all", _load_all)
    monkeypatch.setattr(service.seuils_mod, "charger_tous", _seuils)

    payload = await service.generate(CRMEntite(), None)
    for cle in ("dg", "dg@CI", "dg@BF", "dg@GN"):
        assert cle in payload["sections"], cle
    assert payload["sections"]["dg@CI"]["facts"]["entite"] == "CI"
    assert payload["sections"]["dg@CI"]["analysis"] == ""              # résumé seul
    assert "dir_financier@CI" not in payload["sections"]               # seul le DG a un sélecteur
