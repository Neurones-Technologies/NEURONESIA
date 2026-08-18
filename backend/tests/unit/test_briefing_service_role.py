"""Régénération d'une seule section du briefing.

`store.save` réécrit le fichier ENTIER : le piège de `generate_role` est de
construire son payload de zéro et d'effacer au passage les briefings des quatre
autres rôles jusqu'au cron de minuit — une perte que personne ne verrait avant
le lendemain matin. C'est ce que verrouille le premier test.
"""
import pytest

from modules.uc_briefing import facts, preferences, service, store


class CRMMinimal:
    """Seul le CA YTD répond ; les autres sources tombent, `_safe` les absorbe."""

    async def get_ytd_stats(self, year):
        return {"revenue_xof": 1_000_000_000, "orders_count": 10, "as_of": "2026-08-17"}

    def __getattr__(self, nom):
        async def indisponible(*args, **kwargs):
            raise RuntimeError("source indisponible")

        return indisponible


@pytest.fixture
def store_temporaire(tmp_path, monkeypatch):
    """`store.save/load` acceptent un `base` explicite pour rester testables hors
    disque — on s'en sert plutôt que d'écrire dans le vrai dossier data/."""
    vrai_save, vrai_load = store.save, store.load
    monkeypatch.setattr(store, "save", lambda payload, base=None: vrai_save(payload, base=tmp_path))
    monkeypatch.setattr(store, "load", lambda base=None: vrai_load(base=tmp_path))
    return lambda: vrai_load(base=tmp_path)


@pytest.fixture(autouse=True)
def _preferences_par_defaut(monkeypatch):
    """Aucune base ici : la composition est celle du catalogue."""
    async def _load(role):
        return preferences._document_vide(role)

    async def _load_all():
        return {r: preferences._document_vide(r) for r in service.ROLES}

    monkeypatch.setattr(preferences, "load", _load)
    monkeypatch.setattr(preferences, "load_all", _load_all)


def _snapshot_complet():
    return {
        "generated_at": "2026-08-17T00:00:00+00:00",
        "triggered_by": "schedule",
        "sections": {
            role: {"bullets": [f"puce de {role}"], "resume": [role], "facts": {}, "analysis": ""}
            for role in service.ROLES
        },
        "sections_en_echec": [],
    }


@pytest.mark.asyncio
async def test_generate_role_preserve_les_autres_sections(store_temporaire):
    avant = _snapshot_complet()
    store.save(avant)

    await service.generate_role("dg", CRMMinimal(), None)

    apres = store_temporaire()
    for role in service.ROLES:
        if role == "dg":
            continue
        assert apres["sections"][role] == avant["sections"][role], (
            f"la section « {role} » a été perdue en régénérant le DG"
        )
    assert apres["sections"]["dg"]["bullets"] != avant["sections"]["dg"]["bullets"]


@pytest.mark.asyncio
async def test_generate_role_ne_touche_pas_lhorodatage_global(store_temporaire):
    """`generated_at` racine date le dernier run COMPLET : l'écraser ferait
    croire que les cinq sections datent de l'instant."""
    store.save(_snapshot_complet())
    await service.generate_role("dg", CRMMinimal(), None)

    apres = store_temporaire()
    assert apres["generated_at"] == "2026-08-17T00:00:00+00:00"
    assert apres["sections"]["dg"]["generated_at"] > "2026-08-17T00:00:00+00:00"
    assert apres["sections"]["dg"]["triggered_by"] == "manual"


@pytest.mark.asyncio
async def test_generate_role_sur_store_absent(store_temporaire):
    """Tout premier démarrage : aucun snapshot, pas d'exception."""
    section = await service.generate_role("dg", CRMMinimal(), None)
    assert section["bullets"]
    assert store_temporaire()["sections"]["dg"]


@pytest.mark.asyncio
async def test_generate_role_retire_le_role_des_sections_en_echec(store_temporaire):
    payload = _snapshot_complet()
    payload["sections_en_echec"] = ["dg", "commercial"]
    store.save(payload)

    await service.generate_role("dg", CRMMinimal(), None)

    assert store_temporaire()["sections_en_echec"] == ["commercial"]


@pytest.mark.asyncio
async def test_generate_role_refuse_un_role_inconnu(store_temporaire):
    with pytest.raises(ValueError):
        await service.generate_role("directeur_imaginaire", CRMMinimal(), None)


@pytest.mark.asyncio
async def test_generate_complet_date_chaque_section(store_temporaire):
    await service.generate(CRMMinimal(), None, triggered_by="schedule")
    payload = store_temporaire()
    for role in service.ROLES:
        assert payload["sections"][role]["generated_at"] == payload["generated_at"]


@pytest.mark.asyncio
async def test_composition_enregistree_est_appliquee(store_temporaire, monkeypatch):
    """La préférence lue en base doit atteindre le builder."""
    async def _load(role):
        return {"elements": ["ca_ytd"], "consigne": "", "source": "reglee",
                "updated_by": None, "updated_at": None}

    monkeypatch.setattr(preferences, "load", _load)
    section = await service.generate_role("dg", CRMMinimal(), None)
    assert len(section["bullets"]) == 1


# ---------- traduction préférences → composition (mode « consigne pilote ») ----------


def test_composition_pilote_ouvre_tout_le_pool():
    """Rien de coché + consigne posée : la consigne pilote le contenu, donc
    l'IA doit pouvoir piocher dans tout le catalogue du rôle."""
    compo = service._composition_depuis({"elements": [], "consigne": "Parle des impayés."})
    assert compo.pilote is True
    assert compo.actif("ca_ytd") and compo.actif("nimporte_quel_element")


def test_composition_vide_sans_consigne_reste_inerte():
    """Rien de coché et pas de consigne : pas de pilote — l'aval produit le
    message « Pas assez de données », et la garde du routeur refuse désormais
    d'enregistrer cet état."""
    compo = service._composition_depuis({"elements": [], "consigne": "   "})
    assert compo.pilote is False
    assert not compo.actif("ca_ytd")


def test_composition_avec_elements_ignore_le_pilote():
    compo = service._composition_depuis({"elements": ["ca_ytd"], "consigne": "x"})
    assert compo.pilote is False
    assert compo.actif("ca_ytd") and not compo.actif("rupture_rythme")


def test_composition_sans_document_reste_le_briefing_historique():
    """`None` signifie « aucune préférence » : tout actif, mode normal — à ne
    jamais confondre avec la liste vide."""
    compo = service._composition_depuis(None)
    assert compo.pilote is False
    assert compo.actif("ca_ytd")
