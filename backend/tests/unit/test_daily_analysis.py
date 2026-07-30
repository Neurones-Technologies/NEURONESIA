"""Les narrations IA du cockpit doivent être calculées une fois par jour et
relues en base — pas régénérées à chaque affichage.

Ce qui est vérifié ici : le second appel du jour ne touche plus le modèle, et
rien de fragile n'est figé (repli déterministe, erreur du modèle, état vide)
sinon un incident de quelques minutes gèlerait le cockpit jusqu'au lendemain.
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import core.services.ttl_cache as ttl_cache
from db.database import Base
from db.models import DailyAnalysisModel
from modules.uc_daily_analysis import computations as comp
from modules.uc_daily_analysis import service, store

_MOIS = ["Jan", "Fév", "Mar"]
_VALEURS = [120.0, 180.0, 90.0]


class _FakeLlm:
    def __init__(self, text: str = "Analyse rédigée par le modèle.", boom: bool = False):
        self.calls = 0
        self._text = text
        self._boom = boom

    async def generate(self, **kwargs):
        self.calls += 1
        if self._boom:
            raise RuntimeError("modèle indisponible")
        return self._text


class _FakeCrm:
    """Miroir minimal : juste les agrégats que lisent les 7 narrations."""

    def __init__(self, with_order_lines: bool = False):
        self.with_order_lines = with_order_lines

    async def get_monthly_revenue(self, year):
        return [{"mois": 1, "ca_xof": 120_000_000, "nb_commandes": 3},
                {"mois": 2, "ca_xof": 180_000_000, "nb_commandes": 4},
                {"mois": 3, "ca_xof": 90_000_000, "nb_commandes": 2}]

    async def get_win_rate(self):
        return {"taux_nb_pct": 42.0, "taux_valeur_pct": 51.0}

    async def get_lost_deals(self, limit=50):
        return {
            "nb_total": 3,
            "montant_total_xof": 300_000_000,
            "by_client": [{"client": "CIE", "montant_xof": 200_000_000, "nb": 2}],
        }

    async def list_opportunities(self, limit=500, stage=None):
        return [{
            "opportunite": "Renouvellement parc",
            "client": "CIE",
            "stade": "Négociation",
            "revenu_attendu_xof": 500_000_000,
            "probabilite_pct": 60,
            "deadline": "2030-06-30",
            "commercial": "Assamoi",
            "created_at": "2030-01-05",
        }]

    async def get_margin_stats(self, year=None):
        return {
            "nb_dossiers": 12,
            "backlog_total": 400_000_000,
            "ca_provisoire_total": 1_000_000_000,
            "ca_definitif_total": 700_000_000,
            "perc_marge_provisoire_moyen": 22.0,
            "perc_marge_definitive_moyen": 18.0,
        }

    async def get_top_margin_dossiers(self, limit=20, year=None):
        return [{"ref": "DC/2030/0001", "client": "CIE", "perc_marge_def": 9.0}]

    async def get_unpaid_exposure(self):
        return {
            "nb_factures_impayees": 7,
            "exposition_totale_xof": 250_000_000,
            "retard_90j_montant_xof": 90_000_000,
            "retard_90j_nb_factures": 2,
            "top_10_debiteurs": [
                {"client": "SGCI", "montant_total_xof": 150_000_000, "retard_max_jours": 120},
            ],
        }

    async def get_top_suppliers(self, limit=50):
        return [{"name": "Cisco", "montant_total_xof": 300_000_000,
                 "nb_commandes": 5, "derniere_commande": "2030-05-02"}]

    async def get_order_lines(self):
        # Vide : aucun signal de montée en valeur → la section cross-sell doit
        # être ignorée par le job, jamais figée sur un message d'état.
        return []


async def _run(scenario):
    """Exécute un scénario sur une base mémoire, `store` branché dessus."""
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original = store.AsyncSessionLocal
    store.AsyncSessionLocal = factory
    store._LOCKS.clear()
    ttl_cache._STORE.clear()  # les signaux cross-sell sont mémorisés 120 s globalement
    try:
        return await scenario(factory)
    finally:
        store.AsyncSessionLocal = original
        ttl_cache._STORE.clear()
        await engine.dispose()


async def _rows(factory):
    async with factory() as session:
        return (await session.execute(select(DailyAnalysisModel))).scalars().all()


# ---------- Lecture du jour ----------

def test_deuxieme_affichage_du_jour_ne_rappelle_pas_le_modele():
    llm = _FakeLlm()
    appels_compute = []

    async def scenario(factory):
        async def compute():
            appels_compute.append(1)
            return await comp.trend_analysis(llm, _MOIS, _VALEURS)

        premier = await store.daily_cached(comp.KEY_TREND, "Jan-Marx3", compute)
        second = await store.daily_cached(comp.KEY_TREND, "Jan-Marx3", compute)
        return premier, second, await _rows(factory)

    premier, second, rows = asyncio.run(_run(scenario))

    assert llm.calls == 1, "le modèle ne doit être appelé qu'une fois par jour"
    assert len(appels_compute) == 1
    assert premier["analysis"] == second["analysis"] == "Analyse rédigée par le modèle."
    assert len(rows) == 1
    assert rows[0].source == "llm"
    assert rows[0].triggered_by == "on_demand"
    assert rows[0].snapshot_date == store.today()
    assert rows[0].context["periode_debut"] == "Jan"


def test_variantes_differentes_ne_partagent_pas_une_narration():
    llm = _FakeLlm()

    async def scenario(factory):
        await store.daily_cached(
            comp.KEY_TREND, comp.trend_variant(_MOIS),
            lambda: comp.trend_analysis(llm, _MOIS, _VALEURS),
        )
        mois_longs = _MOIS + ["Avr"]
        await store.daily_cached(
            comp.KEY_TREND, comp.trend_variant(mois_longs),
            lambda: comp.trend_analysis(llm, mois_longs, _VALEURS + [200.0]),
        )
        return await _rows(factory)

    rows = asyncio.run(_run(scenario))
    assert llm.calls == 2
    assert {r.variant for r in rows} == {"Jan-Marx3", "Jan-Avrx4"}


def test_variante_insensible_aux_valeurs_qui_bougent_dans_la_journee():
    """Le mois en cours se remplit à chaque sync Odoo : si la variante dépendait
    des valeurs, chaque affichage retomberait sur un nouvel appel LLM."""
    assert comp.trend_variant(_MOIS) == comp.trend_variant(_MOIS)
    assert comp.trend_variant(_MOIS) != comp.trend_variant(_MOIS + ["Avr"])


# ---------- Ce qui ne doit jamais être figé ----------

def test_repli_deterministe_non_fige_et_reessaye():
    """Modèle absent : le texte de repli est servi mais reste recalculable."""
    async def scenario(factory):
        premier = await store.daily_cached(
            comp.KEY_TREND, "v", lambda: comp.trend_analysis(None, _MOIS, _VALEURS),
        )
        return premier, await _rows(factory)

    premier, rows = asyncio.run(_run(scenario))

    assert premier["source"] == "repli"
    assert premier["analysis"], "le slot doit rester rempli malgré l'absence de modèle"
    assert premier["generated_at"] is None
    assert rows == []


def test_erreur_du_modele_non_figee():
    llm = _FakeLlm(boom=True)

    async def scenario(factory):
        payload = await store.daily_cached(
            comp.KEY_TREND, "v", lambda: comp.trend_analysis(llm, _MOIS, _VALEURS),
        )
        # Un second affichage doit retenter, pas hériter de l'incident.
        await store.daily_cached(
            comp.KEY_TREND, "v", lambda: comp.trend_analysis(llm, _MOIS, _VALEURS),
        )
        return payload, await _rows(factory)

    payload, rows = asyncio.run(_run(scenario))

    assert payload["source"] == "repli"
    assert llm.calls == 2
    assert rows == []


def test_etat_vide_non_fige():
    llm = _FakeLlm()

    async def scenario(factory):
        payload = await store.daily_cached(
            comp.KEY_TREND, "vide", lambda: comp.trend_analysis(llm, _MOIS, [0.0, 0.0, 0.0]),
        )
        return payload, await _rows(factory)

    payload, rows = asyncio.run(_run(scenario))

    assert payload["source"] == "vide"
    assert llm.calls == 0, "un état vide ne consomme pas le modèle"
    assert rows == []


# ---------- Génération quotidienne complète ----------

def test_generate_all_fige_les_sections_et_ignore_les_non_figeables():
    llm = _FakeLlm()
    crm = _FakeCrm()

    async def scenario(factory):
        rapport = await service.generate_all(crm, llm, triggered_by="schedule")
        return rapport, await _rows(factory)

    rapport, rows = asyncio.run(_run(scenario))

    figees = set(rapport["figees"])
    assert figees == {
        comp.KEY_PERFORMANCE, comp.KEY_FORECAST,
        comp.KEY_MARGINS, comp.KEY_UNPAID, comp.KEY_PARTNERS,
    }
    # Aucun signal de montée en valeur dans la fixture → section ignorée.
    assert [i["section"] for i in rapport["ignorees"]] == ["crosssell"]
    assert rapport["ignorees"][0]["raison"] == "vide"

    assert len(rows) == 5
    assert {r.triggered_by for r in rows} == {"schedule"}
    # Variante vide sur les marges : c'est ainsi que les cockpits DF et DO les
    # demandent (sans filtre d'exercice).
    assert next(r for r in rows if r.analysis_key == comp.KEY_MARGINS).variant == ""


def test_generate_all_reproduit_la_variante_de_la_vue_dg():
    """Si la tuile de trajectoire DG est réactivée, la narration doit être figée
    sous la variante que la vue demandera (mêmes libellés de mois)."""
    llm = _FakeLlm()
    crm = _FakeCrm()

    async def scenario(factory):
        key, variant, payload = await service._trend(crm, llm)
        return key, variant, payload

    key, variant, payload = asyncio.run(_run(scenario))

    assert key == comp.KEY_TREND
    assert variant == "Jan-Marx3"
    assert payload["source"] == "llm"
    assert payload["context"]["mois_pic"] == "Fév"


def test_generate_all_idempotent_le_meme_jour():
    """Une relance manuelle remplace les narrations du jour, ne les duplique pas."""
    llm = _FakeLlm()
    crm = _FakeCrm()

    async def scenario(factory):
        await service.generate_all(crm, llm, triggered_by="schedule")
        await service.generate_all(crm, llm, triggered_by="manual")
        return await _rows(factory)

    rows = asyncio.run(_run(scenario))

    assert len(rows) == 5
    assert {r.triggered_by for r in rows} == {"manual"}


def test_endpoint_relit_la_base_apres_le_job():
    """Après le job, l'affichage d'une section ne doit plus appeler le modèle."""
    llm = _FakeLlm()
    crm = _FakeCrm()

    async def scenario(factory):
        await service.generate_all(crm, llm, triggered_by="schedule")
        appels_apres_job = llm.calls
        payload = await store.daily_cached(
            comp.KEY_UNPAID, "", lambda: comp.unpaid_analysis(crm, llm),
        )
        return payload, appels_apres_job, llm.calls, await store.status()

    payload, avant, apres, statut = asyncio.run(_run(scenario))

    assert apres == avant, "la lecture du jour ne consomme aucun token"
    assert payload["analysis"] == "Analyse rédigée par le modèle."
    assert payload["triggered_by"] == "schedule"
    assert {s["analysis_key"] for s in statut} >= {comp.KEY_UNPAID, comp.KEY_MARGINS}
