"""
Test d'intégration de la couche structurée (Phase 1).

Pipeline testé : StructuredExtractor (LLM stubé, sortie tool_use cannée)
 → SQLiteKBAdapter → tables kb_* (SQLite temporaire).
Vérifie : persistance correcte, normalisation montants/dates, filtre « > 200M »,
et IDEMPOTENCE (ré-écriture du même doc_id = zéro doublon).

Autonome (pas de dépendance à pytest-asyncio) : chaque test pilote son propre
event loop via asyncio.run.
"""
import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import adapters.kb.sqlite_kb_adapter as kb_mod
from core.domain.document import DocumentType
from core.ports.llm_gateway import AgentStep
from core.services.structured_extractor import StructuredExtractor
from db import models as m
from db.database import Base


class FakeLLM:
    """Renvoie un tool_call canné pour l'outil demandé (extraction déterministe)."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def agentic_step(self, system, messages, tools, max_tokens=1500):
        return AgentStep(
            stop_reason="tool_use",
            text="",
            tool_calls=[{"id": "t1", "name": tools[0]["name"], "input": self._payload}],
            assistant_message={},
        )


_CV = {
    "personne": {"nom_complet": "Jean Kouassi", "titre_poste": "Chef de projet",
                 "annees_experience_total": 12, "localisation": "Abidjan"},
    "certifications_citees": [{"intitule": "PMP", "organisme": "PMI", "annee": 2019}],
    "experiences": [{"intitule_projet": "Core banking", "client": "SGBCI",
                     "role": "PM", "secteur": "banque",
                     "date_debut": "2020-01", "date_fin": "en cours"}],
    "secteurs_expertise": ["banque", "télécoms"],
}

_ABE = {
    "emetteur_client": "SGBCI", "projet_marche": "Refonte SI",
    "montant": {"valeur": "250M", "devise": "FCFA"},
    "date_debut": "2023-01-15", "date_fin": "2024-06-30",
    "niveau_appreciation": "Très satisfaisant", "secteur": "banque",
    "signataire": {"nom": "M. Diallo", "fonction": "DSI"},
}

_AO = {
    "reference": "AO-2024-007", "intitule": "Fourniture serveurs",
    "maitre_ouvrage": "Ministère", "date_limite_remise": "2024-09-30",
    "budget_estime": {"valeur": "1,2 Md", "devise": "FCFA"},
    "exigences_obligatoires": [{"categorie": "certification", "libelle": "ISO 27001", "obligatoire": True}],
    "references_demandees": [{"description": "Marchés similaires", "nombre_min": 3,
                              "montant_min": "200M", "periode": "3 ans"}],
}


async def _setup(tmp_path, monkeypatch):
    """Crée une base SQLite temporaire + le schéma kb_*, et y branche l'adapter."""
    db_file = tmp_path / "test_kb.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(kb_mod, "AsyncSessionLocal", sm)
    return engine, sm


async def _ingest(payload, doc_type, doc_id, times=1):
    extractor = StructuredExtractor(FakeLLM(payload))
    adapter = kb_mod.SQLiteKBAdapter()
    result = await extractor.extract("texte du document", doc_type)
    assert result is not None
    for _ in range(times):
        await adapter.save_extraction(
            doc_id=doc_id, doc_type=doc_type,
            fichier_source=f"{doc_id}.pdf", hash_sha256="hash123", result=result,
        )
    return result


def test_cv_persist_et_idempotence(tmp_path, monkeypatch):
    async def scenario():
        engine, sm = await _setup(tmp_path, monkeypatch)
        try:
            await _ingest(_CV, DocumentType.CV, "doc-cv-1", times=2)  # 2× → idempotent
            async with sm() as s:
                assert (await s.execute(select(func.count()).select_from(m.KBCvModel))).scalar() == 1
                assert (await s.execute(select(func.count()).select_from(m.KBCvExperienceModel))).scalar() == 1
                assert (await s.execute(select(func.count()).select_from(m.KBCvCertificationModel))).scalar() == 1
                cv = (await s.execute(select(m.KBCvModel))).scalar_one()
                exp = (await s.execute(select(m.KBCvExperienceModel))).scalar_one()
            assert cv.nom_complet == "Jean Kouassi"
            assert cv.annees_experience == 12
            assert exp.secteur == "banque"
            assert exp.en_cours is True
            assert exp.date_fin is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_abe_montant_normalise_et_filtre_superieur_200m(tmp_path, monkeypatch):
    async def scenario():
        engine, sm = await _setup(tmp_path, monkeypatch)
        try:
            await _ingest(_ABE, DocumentType.ABE, "doc-abe-1")
            async with sm() as s:
                abe = (await s.execute(select(m.KBAttestationModel))).scalar_one()
                gt = (await s.execute(
                    select(func.count()).select_from(m.KBAttestationModel)
                    .where(m.KBAttestationModel.montant_valeur > 200_000_000)
                )).scalar()
            assert abe.montant_valeur == 250_000_000.0
            assert abe.montant_devise == "XOF"
            assert abe.date_fin.year == 2024 and abe.date_fin.month == 6
            assert abe.secteur == "banque"
            assert gt == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_ao_references_et_exigences(tmp_path, monkeypatch):
    async def scenario():
        engine, sm = await _setup(tmp_path, monkeypatch)
        try:
            await _ingest(_AO, DocumentType.AO, "doc-ao-1")
            async with sm() as s:
                ao = (await s.execute(select(m.KBAoModel))).scalar_one()
                ref = (await s.execute(select(m.KBAoReferenceDemandeeModel))).scalar_one()
                exig = (await s.execute(select(m.KBAoExigenceModel))).scalar_one()
            assert ao.budget_valeur == 1_200_000_000.0
            assert ref.nombre_min == 3
            assert ref.montant_min_valeur == 200_000_000.0
            assert exig.categorie == "certification"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_confidence_score_renseigne(tmp_path, monkeypatch):
    async def scenario():
        engine, sm = await _setup(tmp_path, monkeypatch)
        try:
            result = await _ingest(_ABE, DocumentType.ABE, "doc-abe-2")
            assert 0.0 < result.score_confiance <= 1.0
        finally:
            await engine.dispose()

    asyncio.run(scenario())
