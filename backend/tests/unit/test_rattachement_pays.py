"""Rattachement par pays : pivot N° FP, replis dans un ordre fixe, jamais deviné.

Chaque test pose une règle et vérifie qu'elle ne s'applique que lorsque toutes
les règles prioritaires sont muettes — et qu'au-delà l'objet reste visible
comme « non rattaché ».
"""
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.services import rattachement
from core.services.entites import EQUIPES_PAYS, sql_equipe_vers_pays
from db.database import Base
from db.models import (
    DossierModel, InvoiceModel, Nt360BcModel, Nt360CommandeModel, Nt360FactureModel,
    Nt360OpportuniteModel, OpportunityModel, PurchaseOrderModel,
)
from db.views import create_views

RECENT = date.today() - timedelta(days=60)
ANCIEN = date.today() - timedelta(days=365 * 3)


def _cmd(fp, entite, am="X", jour=RECENT):
    return Nt360CommandeModel(fp=fp, entite=entite, cas=100, am=am, date_commande=jour, raw={})


def _fac(id_, numero, fp="", filiale="", dc=""):
    return Nt360FactureModel(id=id_, numero=numero, fp=fp, filiale=filiale, dc=dc, amount_ht=10,
                             date_facture=RECENT, raw={})


def _inv(id_, numero, equipe="", residual=10):
    return InvoiceModel(invoice_id=id_, client_id="1", invoice_name=numero, amount=12, amount_residual=residual,
                        status="pending", equipe=equipe, due_date=datetime(2026, 1, 1))


def _opp(id_, fp="", am="", opp_id=None, stage=3):
    return Nt360OpportuniteModel(id=id_, opp_id=opp_id, fp=fp, am=am, stage=stage, stage_label=f"{stage}-X",
                                 amount=50, raw={})


@pytest_asyncio.fixture
async def base():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.run_sync(create_views)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all([
            _cmd("FP/CI", "CI", am="KOFFI"), _cmd("FP/BF", "BF", am="AWA"),
            _cmd("FP/CI2", "CI", am="MULTI"), _cmd("FP/BF2", "BF", am="MULTI"),
            _cmd("FP/VIEUX", "BF", am="KOFFI", jour=ANCIEN),       # hors fenêtre de 24 mois
            # Factures nt360
            _fac("f1", "F/1", fp="FP/CI", filiale="BF", dc="DC/1"),   # filiale prime sur la commande
            _fac("f2", "F/2", fp="FP/CI", dc="DC/2"),                 # pas de filiale → commande
            _fac("f3", "F/3"),                                        # aucun lien
            _fac("f4", "F/4", fp="FP/BF", dc="DC/2"),                 # DC/2 désigne CI ET BF
            # Créances Odoo
            _inv("i1", "F/2", equipe="Vente BF"),   # facture nt360 (CI) prime sur l'équipe (contradiction)
            _inv("i2", "F/ODOO", equipe="Vente BF"),  # pas de facture nt360 → équipe
            _inv("i3", "F/ODOO2", equipe="BU"),       # équipe fonctionnelle → non rattaché
            # Dossiers
            DossierModel(dossier_ref="DC/1", odoo_id=1, backlog=1),
            DossierModel(dossier_ref="DC/2", odoo_id=2, backlog=1),
            DossierModel(dossier_ref="DC/9", odoo_id=9, backlog=1),
            # BC : pays de l'affaire ≠ pays acheteur
            Nt360BcModel(id="b1", bc_number="BC/1", fp="FP/BF", filiale="CI", status="emis", amount_xof=5, raw={}),
            Nt360BcModel(id="b2", bc_number="BC/2", fp="", filiale="CI", status="emis", amount_xof=5, raw={}),
            # Opportunités
            _opp("o_fp", fp="FP/BF", am="KOFFI", stage=6),                  # commande → BF
            _opp("odoo_crm.lead:7", fp="FP/OUVERTE", am="KOFFI", opp_id="opp_7"),  # équipe GN > commercial CI
            OpportunityModel(opp_id="opp_7", odoo_id=7, client_name="C", name="Piste", equipe="Sales GN"),
            _opp("o_com", fp="FP/OUVERTE2", am="koffi "),                   # commercial mono-pays (CI)
            _opp("o_multi", fp="FP/OUVERTE3", am="MULTI"),                  # commercial CI + BF → rien
            _opp("o_awa", am="AWA"),                                         # BF (24 mois)
        ])
        await s.commit()
    async with engine.connect() as c:
        yield c, factory
    await engine.dispose()


async def _par(conn, sql):
    return {r[0]: (r[1], r[2]) for r in (await conn.execute(text(sql))).all()}


def test_correspondance_des_equipes():
    assert EQUIPES_PAYS["Sales CIV"] == "CI" and EQUIPES_PAYS["Vente BF"] == "BF"
    assert "BU" not in EQUIPES_PAYS and "Sales AM" not in EQUIPES_PAYS   # équipes fonctionnelles
    assert "WHEN 'Sales GN' THEN 'GN'" in sql_equipe_vers_pays("x.equipe")


@pytest.mark.asyncio
async def test_factures_filiale_puis_commande(base):
    conn, _ = base
    r = await _par(conn, "SELECT numero, entite, entite_source FROM v_factures")
    assert r["F/1"] == ("BF", "filiale")          # filiale BF, commande CI : la filiale l'emporte
    assert r["F/2"] == ("CI", "commande_fp")
    assert r["F/3"] == ("", "")                   # jamais deviné


@pytest.mark.asyncio
async def test_creances_facture_puis_equipe(base):
    conn, _ = base
    r = await _par(conn, "SELECT invoice_id, entite, entite_source FROM v_creances")
    assert r["i1"] == ("CI", "facture")           # la facture nt360 prime sur l'équipe « Vente BF »
    assert r["i2"] == ("BF", "equipe")
    assert r["i3"] == ("", "")                    # équipe fonctionnelle : aucun pays


@pytest.mark.asyncio
async def test_dossiers_par_dc_un_seul_pays(base):
    conn, _ = base
    r = await _par(conn, "SELECT dossier_ref, entite, entite_source FROM v_dossiers")
    assert r["DC/1"] == ("BF", "dossier_dc")
    assert r["DC/2"] == ("", "")                  # pièces CI et BF : ambigu, non rattaché
    assert r["DC/9"] == ("", "")


@pytest.mark.asyncio
async def test_bc_pays_de_laffaire_et_pays_acheteur(base):
    conn, _ = base
    rows = {r[0]: r[1:] for r in (await conn.execute(text(
        "SELECT name, entite, entite_source, entite_achat FROM v_purchase_orders"))).all()}
    assert rows["BC/1"] == ("BF", "commande_fp", "CI")   # BC émis par la CI pour une affaire BF
    assert rows["BC/2"] == ("", "", "CI")


@pytest.mark.asyncio
async def test_opportunites_commande_equipe_commercial(base):
    conn, _ = base
    r = await _par(conn, "SELECT opp_id, entite, entite_source FROM v_opportunities")
    assert r["nt360:o_fp"] == ("BF", "commande_fp")
    assert r["opp_7"] == ("GN", "equipe")                 # l'équipe passe avant le commercial (CI)
    assert r["nt360:o_com"] == ("CI", "commercial")       # casse et espaces normalisés
    assert r["nt360:o_multi"] == ("", "")                 # commercial sur deux pays : rien
    assert r["nt360:o_awa"] == ("BF", "commercial")


@pytest.mark.asyncio
async def test_fenetre_de_24_mois_du_commercial(base):
    conn, _ = base
    r = await _par(conn, "SELECT am, entite, 1 FROM v_entite_commercial")
    assert r["KOFFI"][0] == "CI"          # sa commande BF date de 3 ans : hors fenêtre
    assert "MULTI" not in r


@pytest.mark.asyncio
async def test_repli_odoo_sans_nt360_reste_sans_entite():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.run_sync(create_views)
    async with AsyncSession(engine) as s:
        s.add_all([OpportunityModel(opp_id="opp_1", odoo_id=1, client_name="C", name="P", equipe="Sales CIV"),
                   PurchaseOrderModel(order_id="po1", client_id="1", client_name="F", name="BC/1", amount=1,
                                      state="purchase")])
        await s.commit()
    async with engine.connect() as c:
        for vue in ("v_opportunities", "v_purchase_orders", "v_sale_orders", "v_factures"):
            rows = (await c.execute(text(f"SELECT entite, entite_source FROM {vue}"))).all()
            assert all(r == ("", "") for r in rows), vue
    await engine.dispose()


def test_filtre_source_liste_blanche():
    from adapters.crm.local_crm_adapter import _source
    assert _source("v_creances") == "v_creances"
    assert _source("v_creances", "BF") == "(SELECT * FROM v_creances WHERE entite = 'BF')"
    with pytest.raises(ValueError):
        _source("invoices", "BF")                 # table sans pays
    with pytest.raises(ValueError):
        _source("v_creances", "CI' OR '1'='1")    # entité hors liste blanche


@pytest.mark.asyncio
async def test_mesure_du_rattachement(base):
    _, factory = base
    m = await rattachement.mesurer(factory)
    cr = m["modules"]["creances_ouvertes"]
    assert cr["total_nb"] == 3 and cr["non_rattache"]["nb"] == 1 and cr["taux_rattachement_pct"] == 66.7
    assert cr["par_pays"]["BF"]["nb"] == 1 and cr["par_source"] == {"facture": 1, "equipe": 1, "non_rattache": 1}
    assert m["contradictions"]["creances_equipe_vs_facture"] == 1     # i1 : équipe BF, facture CI
    assert m["modules"]["dossiers"]["taux_rattachement_pct"] == 33.3
