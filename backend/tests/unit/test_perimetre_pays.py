"""Périmètre pays imposé en un point : la connexion réécrit chaque lecture d'une
vue portant `entite`. Ce qui doit être impossible : qu'un compte BF voie une
ligne CI — par une requête écrite à la main, par l'ORM, par l'assistant, par un
cache, ou par une URL / un en-tête modifiés.
"""
import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.v1.dependencies import poser_perimetre
from core.domain.user import User, UserRole
from core.services import perimetre, ttl_cache
from db.database import Base
from db.models import Nt360CommandeModel
from db.views import VSaleOrderModel, create_views


# ── Réécriture ──────────────────────────────────────────────────────────────

def test_reecriture_garde_lalias():
    sql = perimetre.reecrire("SELECT SUM(o.amount) FROM v_sale_orders o WHERE o.state = 'sale'", "BF")
    assert sql == ("SELECT SUM(o.amount) FROM (SELECT * FROM v_sale_orders WHERE entite = 'BF') o "
                   "WHERE o.state = 'sale'")


def test_reecriture_sans_alias_garde_les_references_orm():
    sql = perimetre.reecrire("SELECT v_sale_orders.amount FROM v_sale_orders WHERE v_sale_orders.x = 1", "CI")
    assert "FROM (SELECT * FROM v_sale_orders WHERE entite = 'CI') AS v_sale_orders WHERE" in sql
    assert sql.startswith("SELECT v_sale_orders.amount")          # référence de colonne intacte


def test_reecriture_jointures_et_virgule():
    sql = perimetre.reecrire(
        "SELECT * FROM clients c JOIN v_creances i ON i.client_id = c.client_id, v_dossiers d", "GN")
    assert "JOIN (SELECT * FROM v_creances WHERE entite = 'GN') i ON" in sql
    assert ", (SELECT * FROM v_dossiers WHERE entite = 'GN') d" in sql
    assert "FROM clients c" in sql                                 # table sans entité : intacte


def test_reecriture_ignore_casse_et_tables_brutes():
    sql = perimetre.reecrire("select * from V_FACTURES join invoices i on 1=1", "BF")
    assert "(SELECT * FROM v_factures WHERE entite = 'BF') AS v_factures join invoices i" in sql


def test_reecriture_refuse_une_entite_hors_liste():
    with pytest.raises(ValueError):
        perimetre.reecrire("SELECT 1 FROM v_factures", "CI' OR '1'='1")
    with pytest.raises(ValueError):
        perimetre.definir("FR")


# ── Règles du périmètre ─────────────────────────────────────────────────────

def _user(role, pays=""):
    return User(id=1, email="x@nt.ci", full_name="X", role=UserRole(role), is_active=True,
                created_at=datetime(2026, 1, 1), pays=pays)


@pytest.mark.parametrize(("role", "pays", "demande", "attendu"), [
    ("commercial", "BF", "CI", "BF"),        # compte pays : l'en-tête ne change rien
    ("dir_financier", "GN", None, "GN"),
    ("dir_commercial", "", "bf", "BF"),      # compte groupe : le sélecteur choisit
    ("dir_commercial", "", None, None),
    ("dir_commercial", "", "FR", None),      # valeur inconnue : groupe
    ("dg", "", "CI", None),                  # DG : toujours groupe sur ses pages
    ("admin", "", "BF", None),
])
def test_regles_du_perimetre(role, pays, demande, attendu):
    async def corps():
        return poser_perimetre(_user(role, pays), demande), perimetre.entite_courante()
    posee, lue = asyncio.run(corps())
    assert posee == attendu and lue == attendu


# ── De bout en bout : la connexion filtre ───────────────────────────────────

@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    perimetre.installer(engine.sync_engine)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.run_sync(create_views)
    f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with f() as s:
        s.add_all([
            Nt360CommandeModel(fp="FP/CI", entite="CI", cas=100, client="A", raw={}),
            Nt360CommandeModel(fp="FP/BF", entite="BF", cas=7, client="B", raw={}),
        ])
        await s.commit()
    yield f
    await engine.dispose()


async def _total_sql(f):
    async with f() as s:
        return (await s.execute(text("SELECT SUM(o.amount) FROM v_sale_orders o"))).scalar()


async def _noms_orm(f):
    async with f() as s:
        return sorted((await s.scalars(select(VSaleOrderModel.name))).all())


@pytest.mark.asyncio
async def test_sans_perimetre_tout_est_visible(factory):
    assert await _total_sql(factory) == 107
    assert await _noms_orm(factory) == ["FP/BF", "FP/CI"]


@pytest.mark.asyncio
async def test_perimetre_filtre_sql_et_orm(factory):
    jeton = perimetre.definir("BF")
    try:
        assert await _total_sql(factory) == 7
        assert await _noms_orm(factory) == ["FP/BF"]
    finally:
        perimetre.reinitialiser(jeton)


@pytest.mark.asyncio
async def test_deux_requetes_simultanees_ne_se_melangent_pas(factory):
    async def requete(entite):
        perimetre.definir(entite)
        await asyncio.sleep(0)                 # entrelace les deux tâches
        return await _total_sql(factory)
    ci, bf = await asyncio.gather(asyncio.create_task(requete("CI")), asyncio.create_task(requete("BF")))
    assert (ci, bf) == (100, 7)


# ── Caches ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_cache_ne_sert_jamais_un_pays_a_un_autre():
    calculs = []

    async def calcul():
        calculs.append(perimetre.entite_courante())
        return perimetre.entite_courante()

    async def lire(entite):
        perimetre.definir(entite)
        return await ttl_cache.cached(("test_perimetre",), 60, calcul)

    resultats = [await asyncio.create_task(lire(e)) for e in ("CI", "BF", "CI", None)]
    assert resultats == ["CI", "BF", "CI", None]
    assert calculs == ["CI", "BF", None]       # le 2e « CI » vient du cache, pas du calcul BF
