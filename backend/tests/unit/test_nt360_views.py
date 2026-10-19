"""Vues v_commandes / v_lignes_commande : nt360 fait foi, Odoo détaille.

L'invariant testé partout : Σ lignes d'un FP = cas nt360. C'est ce qui permet
à une ventilation par constructeur de retomber sur le total nt360.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base
from datetime import date, datetime

from db.models import (
    InvoiceModel, Nt360CommandeModel, Nt360FactureModel, SaleOrderLineModel, SaleOrderModel,
)
from db.views import create_views


def _commande(fp, cas, **kw):
    return Nt360CommandeModel(fp=fp, cas=cas, client=kw.get("client", "CIE"), am="Koffi",
                              bu="SECURED IT", year_po=2026, raw={})


def _order(order_id, name, amount_untaxed):
    return SaleOrderModel(order_id=order_id, client_id="1", client_name="CIE (Odoo)", name=name,
                          amount=amount_untaxed * 1.18, amount_untaxed=amount_untaxed,
                          state="sale", order_lines=[])


def _ligne(line_id, order_id, subtotal, vendor="", display_type=None):
    return SaleOrderLineModel(line_id=line_id, order_id=order_id, product_name=f"P-{line_id}",
                              vendor=vendor, subtotal_xof=subtotal, display_type=display_type)


def _facture(id_, numero, fp, montant, paid=False):
    return Nt360FactureModel(id=id_, numero=numero, fp=fp, client="CIE", amount_ht=montant,
                             date_facture=date(2026, 9, 1), paid=paid, raw={})


def _invoice(id_, numero, montant, status):
    return InvoiceModel(invoice_id=id_, client_id="1", invoice_name=numero, amount=montant,
                        amount_residual=0 if status == "paid" else montant, status=status,
                        invoice_date=datetime(2026, 9, 1), due_date=datetime(2026, 10, 1),
                        payment_date=datetime(2026, 9, 15) if status == "paid" else None)


@pytest_asyncio.fixture
async def conn():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.run_sync(create_views)
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as s:
        s.add_all([
            # conforme : lignes = cas
            _commande("FP/1", 1000), _order("so1", "FP/1", 1000),
            _ligne("l1a", "so1", 600, "cisco"), _ligne("l1b", "so1", 400, "fortinet"),
            _ligne("l1s", "so1", 0, display_type="line_section"),
            # recalée : cas 5 % sous Odoo (taux de change)
            _commande("FP/2", 950), _order("so2", "FP/2", 1000),
            _ligne("l2a", "so2", 750, "cisco"), _ligne("l2b", "so2", 250, "huawei"),
            # absente d'Odoo
            _commande("FP/3", 500),
            # écart hors plage (cas > 2 × lignes) → ajustement
            _commande("FP/4", 1000), _order("so4", "FP/4", 100), _ligne("l4a", "so4", 100, "f5"),
            # cas nul avec lignes → lignes ramenées à 0
            _commande("FP/5", 0), _order("so5", "FP/5", 300), _ligne("l5a", "so5", 300, "cisco"),
            # commande Odoo inconnue de nt360 → invisible
            _order("so9", "FP/9", 777), _ligne("l9a", "so9", 777, "cisco"),
            # Factures : conforme, payée côté nt360 seulement, avoir absent d'Odoo,
            # et une facture Odoo inconnue de nt360 (invisible).
            _facture("F1", "FAC/1", "FP/1", 100, paid=True), _invoice("i1", "FAC/1", 118, "paid"),
            _facture("F2", "FAC/2", "FP/2", 200, paid=True), _invoice("i2", "FAC/2", 236, "pending"),
            _facture("F3", "AV/1", "FP/1", -50, paid=True),
            _invoice("i9", "FAC/9", 999, "pending"),
        ])
        await s.commit()
    async with engine.connect() as c:
        yield c
    await engine.dispose()


async def _rows(conn, sql):
    return [dict(r._mapping) for r in (await conn.execute(text(sql))).all()]


@pytest.mark.asyncio
async def test_rapprochement_par_commande(conn):
    rows = {r["fp"]: r for r in await _rows(conn, "SELECT * FROM v_commandes")}
    assert set(rows) == {"FP/1", "FP/2", "FP/3", "FP/4", "FP/5"}          # FP/9 (Odoo seul) exclu
    assert {fp: r["rapprochement"] for fp, r in rows.items()} == {
        "FP/1": "conforme", "FP/2": "recalee", "FP/3": "absente_odoo",
        "FP/4": "ajustee", "FP/5": "recalee",
    }
    assert rows["FP/2"]["coefficient"] == pytest.approx(0.95)
    assert rows["FP/1"]["client_name"] == "CIE"          # en-tête nt360, pas Odoo
    assert rows["FP/4"]["ajustement"] == 900


@pytest.mark.asyncio
async def test_invariant_somme_des_lignes_egale_cas(conn):
    rows = await _rows(conn, """
        SELECT c.fp, c.montant_ht, COALESCE(SUM(l.montant_ht), 0) AS total
        FROM v_commandes c LEFT JOIN v_lignes_commande l ON l.fp = c.fp
        GROUP BY c.fp, c.montant_ht""")
    for r in rows:
        assert r["total"] == pytest.approx(r["montant_ht"]), r["fp"]


@pytest.mark.asyncio
async def test_recalage_garde_la_ventilation_odoo(conn):
    rows = {r["vendor"]: r for r in await _rows(conn, "SELECT * FROM v_lignes_commande WHERE fp='FP/2'")}
    assert rows["cisco"]["montant_ht"] == pytest.approx(712.5)     # 750 × 0,95
    assert rows["huawei"]["montant_ht"] == pytest.approx(237.5)
    assert rows["cisco"]["montant_ht_odoo"] == 750                  # montant d'origine conservé


@pytest.mark.asyncio
async def test_lignes_de_mise_en_forme_exclues(conn):
    ids = {r["line_id"] for r in await _rows(conn, "SELECT line_id FROM v_lignes_commande WHERE fp='FP/1'")}
    assert ids == {"l1a", "l1b"}


@pytest.mark.asyncio
async def test_ajustement_non_detaille_sans_marque(conn):
    rows = await _rows(conn, "SELECT * FROM v_lignes_commande WHERE origine='ajustement' ORDER BY fp")
    assert [(r["fp"], r["montant_ht"], r["vendor"], r["product_name"]) for r in rows] == [
        ("FP/3", 500, "", "non détaillé"),
        ("FP/4", 900, "", "non détaillé"),
    ]
    [f5] = await _rows(conn, "SELECT montant_ht FROM v_lignes_commande WHERE fp='FP/4' AND origine='odoo'")
    assert f5["montant_ht"] == 100                       # ligne Odoo non déformée


@pytest.mark.asyncio
async def test_commande_odoo_absente_de_nt360_hors_chiffres(conn):
    [r] = await _rows(conn, "SELECT SUM(montant_ht) AS t FROM v_lignes_commande WHERE vendor='cisco'")
    assert r["t"] == pytest.approx(600 + 712.5 + 0)      # sans les 777 de FP/9


@pytest.mark.asyncio
async def test_v_sale_orders_expose_nt360_au_format_historique(conn):
    rows = {r["name"]: r for r in await _rows(conn, "SELECT * FROM v_sale_orders")}
    assert set(rows) == {"FP/1", "FP/2", "FP/3", "FP/4", "FP/5"}       # FP/9 (Odoo seul) exclu
    fp2 = rows["FP/2"]
    assert (fp2["order_id"], fp2["amount"], fp2["client_name"], fp2["salesperson_name"], fp2["state"]) == (
        "so2", 950, "CIE", "Koffi", "sale")                             # HT nt360, libellés nt360
    assert rows["FP/3"]["order_id"] == "nt360:FP/3" and rows["FP/3"]["client_id"] == ""


@pytest.mark.asyncio
async def test_date_de_repli_dans_lexercice_nt360(conn):
    # FP/3 : ni date nt360 ni commande Odoo → 31/12 de year_po, pour rester
    # dans les totaux annuels.
    [r] = await _rows(conn, "SELECT date_order FROM v_sale_orders WHERE name='FP/3'")
    assert r["date_order"] == "2026-12-31 00:00:00.000000"


@pytest.mark.asyncio
async def test_orm_lit_la_vue_comme_sale_orders(conn):
    from datetime import datetime
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from db.views import VSaleOrderModel
    async with AsyncSession(conn) as s:
        so = await s.get(VSaleOrderModel, "so1")
    assert so.name == "FP/1" and so.amount == 1000 and isinstance(so.order_lines, list)
    assert so.date_order is None or isinstance(so.date_order, datetime)


@pytest.mark.asyncio
async def test_vues_recreees_sans_erreur(conn):
    await conn.run_sync(create_views)                    # idempotent au redémarrage
    assert len(await _rows(conn, "SELECT * FROM v_commandes")) == 5


# ── Factures ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v_factures_nt360_fait_foi_et_rapproche_odoo(conn):
    rows = {r["numero"]: r for r in await _rows(conn, "SELECT * FROM v_factures")}
    assert set(rows) == {"FAC/1", "FAC/2", "AV/1"}                      # FAC/9 (Odoo seul) exclue
    assert {n: r["rapprochement"] for n, r in rows.items()} == {
        "FAC/1": "conforme", "FAC/2": "statut_divergent", "AV/1": "absente_odoo"}
    f1 = rows["FAC/1"]
    assert (f1["amount"], f1["base_montant"], f1["montant_ttc_odoo"]) == (100, "HT", 118)
    assert f1["payment_date"] is not None                                # date de solde lue dans Odoo
    assert rows["AV/1"]["client_id"] == "1"                              # repris de la commande via fp
    [t] = await _rows(conn, "SELECT SUM(amount) AS t FROM v_factures")
    assert t["t"] == 250                                                 # avoir déduit


# ── Repli Odoo tant que nt360 n'a jamais été synchronisé ────────────────────

@pytest_asyncio.fixture
async def conn_odoo_seul():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.run_sync(create_views)
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as s:
        annulee = _order("so3", "FP/3", 300)
        annulee.state = "cancel"
        s.add_all([
            _order("so1", "FP/1", 1000), _ligne("l1", "so1", 1000, "cisco"),
            annulee, _ligne("l3", "so3", 300, "cisco"),
            _invoice("i1", "FAC/1", 118, "paid"),
            InvoiceModel(invoice_id="i2", client_id="1", invoice_name="FAC/2", amount=50,
                         amount_residual=50, status="cancelled", due_date=datetime(2026, 10, 1)),
        ])
        await s.commit()
    async with engine.connect() as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_repli_odoo_sans_donnees_nt360(conn_odoo_seul):
    so = await _rows(conn_odoo_seul, "SELECT name, amount, state FROM v_sale_orders ORDER BY name")
    assert so == [{"name": "FP/1", "amount": pytest.approx(1180), "state": "sale"},   # TTC Odoo, inchangé
                  {"name": "FP/3", "amount": pytest.approx(354), "state": "cancel"}]  # état filtré par les lecteurs
    lignes = await _rows(conn_odoo_seul, "SELECT fp, montant_ht FROM v_lignes_commande")
    assert lignes == [{"fp": "FP/1", "montant_ht": 1000}]                 # annulée écartée
    fac = await _rows(conn_odoo_seul, "SELECT numero, amount, base_montant FROM v_factures")
    assert fac == [{"numero": "FAC/1", "amount": 118, "base_montant": "TTC"}]


# ── Achats (BC) ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def conn_achats():
    from db.models import Nt360BcModel, PurchaseOrderModel
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.run_sync(create_views)
    from sqlalchemy.ext.asyncio import AsyncSession
    bc = lambda id_, num, status, montant, **kw: Nt360BcModel(
        id=id_, bc_number=num, status=status, amount_xof=montant, supplier="MICROSFT",
        date_in=kw.get("date_in", date(2026, 3, 1)), dc=kw.get("dc", ""), raw={})
    async with AsyncSession(engine) as s:
        s.add_all([
            bc("b1", "BC/1", "livre", 1000, dc="DC/2026/1"),
            bc("b2", "", "a_emettre", 500, date_in=None),          # pas encore engagé
            bc("b3", "BC/3", "annule", 300),
            bc("b4", "BC/4", "emis", 200),                          # absent d'Odoo
            PurchaseOrderModel(order_id="po1", client_id="77", client_name="Microsoft CSP", name="BC/1",
                               amount=1180, state="purchase", date_order=datetime(2026, 3, 1)),
            PurchaseOrderModel(order_id="po9", client_id="78", client_name="AUTRE", name="BC/9",
                               amount=999, state="purchase", date_order=datetime(2026, 3, 1)),
        ])
        await s.commit()
    async with engine.connect() as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_v_purchase_orders_ne_garde_que_les_bc_engages(conn_achats):
    rows = {r["name"]: r for r in await _rows(conn_achats, "SELECT * FROM v_purchase_orders")}
    assert set(rows) == {"BC/1", "BC/4"}                 # ni à émettre, ni annulé, ni Odoo seul
    b1 = rows["BC/1"]
    assert (b1["amount"], b1["order_id"], b1["client_id"], b1["client_name"], b1["dossier_id"]) == (
        1000, "po1", "77", "Microsoft CSP", "DC/2026/1")  # HT nt360, fournisseur Odoo, DC nt360
    assert rows["BC/4"]["client_name"] == "MICROSFT" and rows["BC/4"]["order_id"] == "nt360:b4"


@pytest.mark.asyncio
async def test_v_purchase_orders_repli_odoo(conn_odoo_seul):
    from db.models import PurchaseOrderModel
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(conn_odoo_seul) as s:
        s.add(PurchaseOrderModel(order_id="po1", client_id="77", client_name="X", name="BC/1",
                                 amount=1180, state="purchase"))
        await s.commit()
    rows = await _rows(conn_odoo_seul, "SELECT name, amount FROM v_purchase_orders")
    assert rows == [{"name": "BC/1", "amount": 1180}]


# ── Opportunités ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v_opportunities_nt360_fait_foi_et_odoo_complete(conn):
    from db.models import Nt360OpportuniteModel, OpportunityModel
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(conn) as s:
        s.add_all([
            Nt360OpportuniteModel(id="odoo_crm.lead:7", opp_id="opp_7", client="CIE", am="KOFFI",
                                  amount=500, stage=3, stage_label="3-Transmise", probability=40,
                                  closing_date=date(2026, 12, 31), source="odoo", raw={}),
            Nt360OpportuniteModel(id="saisie_genord_FP_1", client="CIE", am="KOFFI", fp="FP/1",
                                  amount=1000, stage=6, stage_label="6-Gagné", probability=100,
                                  source="saisie", lecture="unitaire", raw={}),
            OpportunityModel(opp_id="opp_7", odoo_id=7, client_id="1", client_name="CIE (Odoo)",
                             name="Refresh réseau", stage="Transmise", expected_revenue=9999,
                             created_at=datetime(2026, 1, 5), write_date=datetime(2026, 9, 1)),
            # Écartée par nt360 : ne doit apparaître nulle part
            OpportunityModel(opp_id="opp_8", odoo_id=8, client_id="1", client_name="CIE",
                             name="Vieille piste", stage="Perdu", expected_revenue=5e9),
        ])
        await s.commit()
    rows = {r["opp_id"]: r for r in await _rows(conn, "SELECT * FROM v_opportunities")}
    assert set(rows) == {"opp_7", "nt360:saisie_genord_FP_1"}
    o7 = rows["opp_7"]
    assert (o7["expected_revenue"], o7["stage"], o7["salesperson_name"], o7["client_name"]) == (
        500, "3-Transmise", "KOFFI", "CIE")                                # nt360 fait foi
    assert o7["name"] == "Refresh réseau" and o7["created_at"] is not None  # Odoo complète
    assert o7["deadline"] == "2026-12-31 00:00:00.000000"
    saisie = rows["nt360:saisie_genord_FP_1"]
    assert saisie["client_id"] == "1" and saisie["fp"] == "FP/1"           # client_id via la commande


@pytest.mark.asyncio
async def test_v_opportunities_repli_odoo(conn_odoo_seul):
    from db.models import OpportunityModel
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(conn_odoo_seul) as s:
        s.add(OpportunityModel(opp_id="opp_1", odoo_id=1, client_id="1", client_name="CIE",
                               name="Piste", stage="Qualification", expected_revenue=10))
        await s.commit()
    assert await _rows(conn_odoo_seul, "SELECT opp_id, expected_revenue FROM v_opportunities") == [
        {"opp_id": "opp_1", "expected_revenue": 10}]
