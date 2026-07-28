"""LocalCRMAdapter.get_supplier_intelligence — les 5 indicateurs différenciants
fournisseurs (crédit/consommation, cash 30-60-90j, marge de sous-traitance liée à
une mission, fiabilité de paiement réelle, risque de rupture à fournisseur unique).
Utilise une vraie base SQLite temporaire (pas de fake session) : la logique repose
sur plusieurs jointures SQL brutes entre tables, plus fiable à vérifier bout en bout
qu'à mocker requête par requête."""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

import adapters.crm.local_crm_adapter as local_crm_adapter
from adapters.crm.local_crm_adapter import LocalCRMAdapter
from db.database import Base
from db.models import PurchaseOrderModel, SupplierModel, SupplierInvoiceModel, DossierModel


@pytest.fixture
def db_session_factory(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    monkeypatch.setattr(local_crm_adapter, "AsyncSessionLocal", session_factory)
    return session_factory


def _seed(session_factory, *, credit_limit=10_000_000, use_credit_limit=True):
    now = datetime.utcnow()

    async def _run():
        async with session_factory() as session:
            session.add(SupplierModel(
                supplier_id="42", odoo_id=42, name="ACME Sous-traitance",
                credit_limit=credit_limit, use_partner_credit_limit=use_credit_limit,
                payment_term_name="30 jours date de facture", payment_term_days=30,
                supplier_rank=1,
            ))
            session.add(DossierModel(
                dossier_ref="DC/2026/0001", odoo_id=1001, client_name="Banque X",
                state="confirmed", marge_definitive=0.0, marge_provisoire=5_000_000.0,
                marge_previsionnelle=4_000_000.0,
            ))
            session.add(PurchaseOrderModel(
                order_id="po_1", odoo_id=1, client_id="42", client_name="ACME Sous-traitance",
                name="BC/1", amount=2_000_000.0, date_order=now, state="purchase",
                dossier_id="DC/2026/0001",
            ))
            # Facture ouverte à 15j (bucket 30j), une à 75j (bucket 90j)
            session.add(SupplierInvoiceModel(
                invoice_id="si_1", odoo_id=1, supplier_id="42", supplier_name="ACME Sous-traitance",
                amount=3_000_000.0, amount_residual=3_000_000.0, due_date=now + timedelta(days=15),
                payment_state="not_paid",
            ))
            session.add(SupplierInvoiceModel(
                invoice_id="si_2", odoo_id=2, supplier_id="42", supplier_name="ACME Sous-traitance",
                amount=1_000_000.0, amount_residual=1_000_000.0, due_date=now + timedelta(days=75),
                payment_state="not_paid",
            ))
            # Facture soldée AVEC retard réel de 10 jours vs échéance
            paid_due = now - timedelta(days=40)
            session.add(SupplierInvoiceModel(
                invoice_id="si_3", odoo_id=3, supplier_id="42", supplier_name="ACME Sous-traitance",
                amount=500_000.0, amount_residual=0.0, due_date=paid_due,
                payment_date=paid_due + timedelta(days=10), payment_state="paid",
            ))
            await session.commit()

    asyncio.run(_run())


def test_ligne_de_credit_vs_consommation(db_session_factory):
    _seed(db_session_factory, credit_limit=10_000_000, use_credit_limit=True)

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    assert acme["credit_limit_xof"] == 10_000_000
    assert acme["encours_du_xof"] == 4_000_000  # 3M (15j) + 1M (75j), la payée exclue
    assert acme["taux_consommation_credit_pct"] == 40.0


def test_cash_previsionnel_30_60_90(db_session_factory):
    _seed(db_session_factory)

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    assert acme["cash_30j_xof"] == 3_000_000
    assert acme["cash_90j_xof"] == 1_000_000
    assert acme["cash_60j_xof"] == 0


def test_marge_de_sous_traitance_via_dossier_lie(db_session_factory):
    _seed(db_session_factory)

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    # marge_definitive=0 → repli sur marge_provisoire (5M), pas la prévisionnelle
    assert acme["marge_sous_traitance_xof"] == 5_000_000
    assert acme["nb_dossiers_lies"] == 1


def test_fiabilite_paiement_retard_reel(db_session_factory):
    _seed(db_session_factory)

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    assert acme["retard_moyen_jours"] == 10.0
    assert acme["payment_term_days"] == 30


def test_risque_rupture_fournisseur_unique_sur_dossier_actif(db_session_factory):
    _seed(db_session_factory)

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    assert acme["dossiers_a_risque_fournisseur_unique"] == 1


def test_risque_rupture_absent_si_plusieurs_fournisseurs_sur_le_dossier(db_session_factory):
    _seed(db_session_factory)

    async def _add_second_supplier():
        async with db_session_factory() as session:
            session.add(PurchaseOrderModel(
                order_id="po_2", odoo_id=2, client_id="99", client_name="Autre Fournisseur",
                name="BC/2", amount=500_000.0, date_order=datetime.utcnow(), state="purchase",
                dossier_id="DC/2026/0001",
            ))
            await session.commit()

    asyncio.run(_add_second_supplier())

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    assert acme["dossiers_a_risque_fournisseur_unique"] == 0


def test_taux_de_dependance_pct(db_session_factory):
    _seed(db_session_factory)

    async def _add_second_supplier_po():
        async with db_session_factory() as session:
            session.add(PurchaseOrderModel(
                order_id="po_3", odoo_id=3, client_id="99", client_name="Petit Fournisseur",
                name="BC/3", amount=2_000_000.0, date_order=datetime.utcnow(), state="purchase",
            ))
            await session.commit()

    asyncio.run(_add_second_supplier_po())

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    # 2M (ACME) sur 4M au total (2M + 2M) = 50%
    assert acme["taux_dependance_pct"] == 50.0


def test_pas_de_credit_limit_configure_ne_calcule_pas_de_taux(db_session_factory):
    _seed(db_session_factory, credit_limit=None, use_credit_limit=False)

    result = asyncio.run(LocalCRMAdapter().get_supplier_intelligence())

    acme = next(s for s in result if s["name"] == "ACME Sous-traitance")
    assert acme["taux_consommation_credit_pct"] is None  # honnête : pas inventé
