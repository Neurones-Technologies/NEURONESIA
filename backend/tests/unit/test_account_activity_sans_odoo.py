"""get_account_activity — commandes nt360 sans contrepartie Odoo.

Le `client_id` ne vient que d'Odoo : une commande saisie à la main dans nt360,
ou pas encore dans le miroir, n'en a pas. Écartée, elle faisait retomber le CA
du portefeuille sous celui de nt360 (5,40 Md contre 5,475 pour la CI en 2026).
"""
import asyncio
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import adapters.crm.local_crm_adapter as local_crm_adapter
from adapters.crm.local_crm_adapter import LocalCRMAdapter
from db.database import Base
from db.models import ClientModel, Nt360CommandeModel, SaleOrderModel
from db.views import create_views


@pytest.fixture
def adapter(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def _cmd(fp, client, cas):
        return Nt360CommandeModel(fp=fp, client=client, cas=cas, entite="CI", year_po=2026,
                                  date_commande=date(2026, 3, 1), raw={})

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(create_views)
        async with factory() as s:
            s.add_all([
                ClientModel(client_id="1", name="GT BANK"),
                ClientModel(client_id="2", name="ECOBANK CI"),
                ClientModel(client_id="3", name="ECOBANK"),
                ClientModel(client_id="4", name="ECOBANK"),
                SaleOrderModel(order_id="o1", name="FP/1", client_id="1", client_name="GT BANK",
                               amount=100.0, state="sale", date_order=datetime(2026, 2, 1)),
                _cmd("FP/1", "GT BANK", 100.0),     # contrepartie Odoo
                _cmd("FP/2", "GT BANK", 40.0),      # absente d'Odoo, nom unique dans clients
                _cmd("FP/3", "ECOBANK", 25.0),      # absente d'Odoo, nom ambigu (2 comptes)
                _cmd("FP/4", "ECOBANK", 5.0),
            ])
            await s.commit()

    asyncio.run(_setup())
    monkeypatch.setattr(local_crm_adapter, "AsyncSessionLocal", factory)
    return LocalCRMAdapter()


@pytest.mark.asyncio
async def test_aucune_commande_nt360_nest_perdue(adapter):
    comptes = await adapter.get_account_activity(as_of=date(2026, 10, 19))
    assert sum(c["ca_exercice_xof"] for c in comptes) == 170


@pytest.mark.asyncio
async def test_nom_unique_rattache_nom_ambigu_mis_a_part(adapter):
    comptes = await adapter.get_account_activity(as_of=date(2026, 10, 19))
    actifs = {(c["compte"], c["client_id"]): c for c in comptes if c["nb_commandes"]}

    gt = actifs[("GT BANK", "1")]
    assert gt["ca_exercice_xof"] == 140 and gt["nb_commandes"] == 2 and not gt["hors_referentiel"]

    # Jamais fusionnée avec un des deux comptes ECOBANK : servie à part, signalée.
    eco = actifs[("ECOBANK", None)]
    assert eco["ca_exercice_xof"] == 30 and eco["hors_referentiel"]
