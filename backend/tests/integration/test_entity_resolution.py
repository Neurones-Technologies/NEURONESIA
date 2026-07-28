"""
Test d'intégration de la résolution d'entités (Phase 2) — cas clé du playbook.

Scénario : le MÊME projet (et le même client) apparaît dans un appel d'offres,
un PV de recette et une attestation, avec des libellés variant en casse, accents
et ponctuation. On vérifie qu'une seule entité canonique est créée et que les
trois faits pointent le même `*_ref_id`. Plus un cas de revue humaine (`pending`).

Autonome (pas de pytest-asyncio) : chaque test pilote son event loop.
"""
import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import adapters.kb.sqlite_kb_adapter as kb_mod
from core.domain.document import DocumentType
from core.ports.llm_gateway import AgentStep
from core.services.entity_resolver import EntityResolver
from core.services.structured_extractor import StructuredExtractor
from db import models as m
from db.database import Base


class FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    async def agentic_step(self, system, messages, tools, max_tokens=1500):
        return AgentStep(stop_reason="tool_use", text="",
                         tool_calls=[{"id": "t", "name": tools[0]["name"], "input": self._payload}],
                         assistant_message={})


# Mêmes client/projet, libellés volontairement variés (casse/accents/ponctuation).
_AO = {"reference": "AO-1", "intitule": "Refonte du Système d'Information",
       "maitre_ouvrage": "Banque Atlantique"}
_PV = {"projet_associe": "refonte du systeme d'information", "client": "BANQUE ATLANTIQUE",
       "type_recette": "definitive", "statut_global": "accepte"}
_ABE = {"emetteur_client": "Banque Atlantique S.A.", "projet_marche": "REFONTE DU SYSTÈME D’INFORMATION",
        "montant": {"valeur": "300M", "devise": "FCFA"}, "secteur": "banque"}


async def _setup(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'kb.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(kb_mod, "AsyncSessionLocal", sm)
    return engine, sm


async def _ingest_and_resolve(payload, doc_type, doc_id, resolver):
    adapter = kb_mod.SQLiteKBAdapter()
    result = await StructuredExtractor(FakeLLM(payload)).extract("texte", doc_type)
    await adapter.save_extraction(doc_id=doc_id, doc_type=doc_type,
                                  fichier_source=f"{doc_id}.pdf", hash_sha256="h", result=result)
    await adapter.resolve_document(doc_id, doc_type, resolver)


def test_meme_projet_dans_ao_pv_abe_est_fusionne(tmp_path, monkeypatch):
    async def scenario():
        engine, sm = await _setup(tmp_path, monkeypatch)
        try:
            resolver = EntityResolver()  # libellés normalisent à l'identique → match exact
            await _ingest_and_resolve(_AO, DocumentType.AO, "ao1", resolver)
            await _ingest_and_resolve(_PV, DocumentType.PV_RECETTE, "pv1", resolver)
            await _ingest_and_resolve(_ABE, DocumentType.ABE, "abe1", resolver)

            async with sm() as s:
                n_projets = (await s.execute(select(func.count()).select_from(m.KBProjetModel))).scalar()
                n_clients = (await s.execute(select(func.count()).select_from(m.KBClientModel))).scalar()
                ao = await s.get(m.KBAoModel, "ao1")
                pv = await s.get(m.KBPvRecetteModel, "pv1")
                abe = await s.get(m.KBAttestationModel, "abe1")

            assert n_projets == 1, "le même projet doit produire UNE seule entité canonique"
            assert n_clients == 1, "le même client doit produire UNE seule entité canonique"
            assert ao.projet_ref_id is not None
            assert ao.projet_ref_id == pv.projet_ref_id == abe.projet_ref_id
            assert ao.client_ref_id == pv.client_ref_id == abe.client_ref_id
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_rapprochement_incertain_va_en_revue(tmp_path, monkeypatch):
    async def scenario():
        engine, sm = await _setup(tmp_path, monkeypatch)
        try:
            # ratio constant 0.80 → entre review(0.75) et auto(0.90) ⇒ pending.
            resolver = EntityResolver(ratio_fn=lambda a, b: 0.80)
            await _ingest_and_resolve(
                {"emetteur_client": "Société Alpha", "projet_marche": "P1"},
                DocumentType.ABE, "abe-a", resolver)
            await _ingest_and_resolve(
                {"emetteur_client": "Société Alpha Beta", "projet_marche": "P2"},
                DocumentType.ABE, "abe-b", resolver)

            adapter = kb_mod.SQLiteKBAdapter()
            pending = await adapter.list_pending("client")
            async with sm() as s:
                abe_b = await s.get(m.KBAttestationModel, "abe-b")

            assert len(pending) == 1, "le second client ambigu doit partir en revue"
            assert abe_b.client_ref_id is None, "un fait en attente de revue n'est pas lié"

            # Validation humaine → l'alias devient confirmed et sort de la file.
            await adapter.confirm_alias(pending[0]["id"], pending[0]["suggested_entity_id"])
            assert await adapter.list_pending("client") == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())
