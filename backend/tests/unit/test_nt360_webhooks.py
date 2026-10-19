"""Webhooks nt360 : jeton d'URL, idempotence (event + identifiant), relecture.

La doc v1 : « un même événement peut arriver deux fois, traitez-le de façon
idempotente » et « relisez l'élément concerné par son identifiant ». Le
contenu de `data` ne doit donc jamais être écrit tel quel.
"""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.v1 import webhooks
from config.settings import settings
from db.database import Base
from db.models import Nt360CommandeModel, Nt360OpportuniteModel, Nt360WebhookEvenementModel
from jobs import nt360_webhook_job

JETON = "s3cr3t-nt360"
OPP_WON = {"event": "opp_won", "ts": "2026-10-19T08:00:00.000Z",
           "data": {"oppId": "odoo_crm.lead:12900", "client": "FORGÉ", "amount": 1, "fp": "FP/2026/142"}}


class FauxAdapter:
    def __init__(self, opp=None, commande=None, erreur=None):
        self.opp, self.commande, self.erreur, self.lus = opp, commande, erreur, []

    async def get(self, ressource, ident):
        self.lus.append((ressource, ident))
        if self.erreur:
            raise self.erreur
        return {"opportunities": self.opp, "commandes": self.commande}[ressource]


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(nt360_webhook_job, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "nt360_webhook_token", JETON)

    app = FastAPI()
    app.include_router(webhooks.router, prefix="/v1")

    class Container:
        nt360_adapter = FauxAdapter(
            opp={"id": "odoo_crm.lead:12900", "oppId": "odoo_crm.lead:12900", "client": "CIE", "am": "KOFFI",
                 "fp": "FP/2026/142", "amount": 48_500_000, "stage": 6, "stageLabel": "6-Gagné",
                 "probability": 100},
            commande={"fp": "FP/2026/142", "client": "CIE", "cas": 48_500_000, "raf": 48_500_000},
        )
    app.state.container = Container()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, factory, Container.nt360_adapter
    await client.aclose()
    await engine.dispose()


async def _evenements(factory):
    async with factory() as s:
        return {e.cle: e for e in (await s.scalars(select(Nt360WebhookEvenementModel))).all()}


# ── Jeton ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jeton_faux_ou_absent_rend_404(env, monkeypatch):
    client, _, _ = env
    assert (await client.post("/v1/webhooks/nt360/mauvais", json=OPP_WON)).status_code == 404
    monkeypatch.setattr(settings, "nt360_webhook_token", "")
    assert (await client.post(f"/v1/webhooks/nt360/{JETON}", json=OPP_WON)).status_code == 404


# ── Idempotence et relecture ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_opp_won_relit_opportunite_et_commande_sans_ecrire_data(env):
    client, factory, adapter = env
    r = await client.post(f"/v1/webhooks/nt360/{JETON}", json=OPP_WON)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert adapter.lus == [("opportunities", "odoo_crm.lead:12900"), ("commandes", "FP/2026/142")]
    async with factory() as s:
        opp = await s.get(Nt360OpportuniteModel, "odoo_crm.lead:12900")
        cmd = await s.get(Nt360CommandeModel, "FP/2026/142")
    assert opp.client == "CIE" and opp.amount == 48_500_000          # relu, pas « FORGÉ » / 1
    assert opp.opp_id == "opp_12900" and opp.lecture == "unitaire"
    assert cmd.cas == 48_500_000
    ev = (await _evenements(factory))["opp_won:odoo_crm.lead:12900"]
    assert ev.statut == "traite" and ev.ts is not None


@pytest.mark.asyncio
async def test_doublon_ignore(env):
    client, factory, adapter = env
    await client.post(f"/v1/webhooks/nt360/{JETON}", json=OPP_WON)
    r = await client.post(f"/v1/webhooks/nt360/{JETON}", json=OPP_WON)
    assert r.json()["status"] == "duplicate"
    assert len(adapter.lus) == 2                                        # une seule relecture
    assert (await _evenements(factory))["opp_won:odoo_crm.lead:12900"].nb_receptions == 2


@pytest.mark.asyncio
async def test_reception_apres_echec_est_retraitee(env):
    from adapters.nt360.nt360_adapter import Nt360Error
    _, factory, _ = env
    cle = await nt360_webhook_job.enregistrer("opp_won", OPP_WON["data"], OPP_WON["ts"])
    assert await nt360_webhook_job.traiter(cle, FauxAdapter(erreur=Nt360Error("500", 500))) == "erreur"
    # nt360 renvoie : l'événement en erreur doit être retraité, pas ignoré
    assert await nt360_webhook_job.enregistrer("opp_won", OPP_WON["data"], OPP_WON["ts"]) == cle
    ok = FauxAdapter(opp={"id": "odoo_crm.lead:12900", "client": "CIE", "stage": 6}, commande=None)
    assert await nt360_webhook_job.traiter(cle, ok) == "traite"


@pytest.mark.asyncio
async def test_approval_decided_journalise(env):
    client, factory, adapter = env
    r = await client.post(f"/v1/webhooks/nt360/{JETON}", json={
        "event": "approval_decided", "data": {"approvalId": "ap1", "decision": "approved"}})
    assert r.json()["status"] == "accepted" and adapter.lus == []
    assert (await _evenements(factory))["approval_decided:ap1"].statut == "traite"


@pytest.mark.asyncio
async def test_evenement_inconnu_ou_sans_identifiant_ignore_en_2xx(env):
    client, factory, _ = env
    r1 = await client.post(f"/v1/webhooks/nt360/{JETON}", json={"event": "invoice_paid", "data": {"id": 1}})
    r2 = await client.post(f"/v1/webhooks/nt360/{JETON}", json={"event": "opp_won", "data": {}})
    assert (r1.status_code, r1.json()["status"]) == (200, "ignored")
    assert (r2.status_code, r2.json()["status"]) == (200, "ignored")
    assert await _evenements(factory) == {}


@pytest.mark.asyncio
async def test_sans_adapter_lechec_est_journalise(env):
    _, factory, _ = env
    cle = await nt360_webhook_job.enregistrer("opp_won", OPP_WON["data"], None)
    assert await nt360_webhook_job.traiter(cle, None) == "erreur"
    assert "désactivée" in (await _evenements(factory))[cle].detail
