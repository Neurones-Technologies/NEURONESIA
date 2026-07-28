"""
Adapter SQL lecture seule (Phase 3) — exécution réelle sur SQLite temporaire.

Vérifie : écriture bloquée au niveau connexion (mode=ro + query_only),
whitelist (refus de `users`), et les requêtes types du playbook §6
(analytique « > 200M » et croisement « PMP ET bancaire »).

Autonome (asyncio.run).
"""
import asyncio
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from adapters.kb.readonly_sql_adapter import ReadOnlySqlAdapter
from core.services.sql_guard import SqlGuardError
from core.services.sql_schema import KB_TABLES
from db import models as m
from db.database import Base


async def _seed(db_file):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        # Attestations (analytique « > 200M »)
        s.add_all([
            m.KBAttestationModel(doc_id="a1", fichier_source="a1.pdf", emetteur_client="SGBCI",
                                 montant_valeur=300_000_000, montant_devise="XOF",
                                 date_fin=datetime(2024, 6, 30), secteur="banque"),
            m.KBAttestationModel(doc_id="a2", fichier_source="a2.pdf", emetteur_client="MTN",
                                 montant_valeur=150_000_000, montant_devise="XOF",
                                 date_fin=datetime(2024, 1, 10), secteur="telecom"),
            m.KBAttestationModel(doc_id="a3", fichier_source="a3.pdf", emetteur_client="BICICI",
                                 montant_valeur=250_000_000, montant_devise="XOF",
                                 date_fin=datetime(2023, 9, 1), secteur="banque"),
        ])
        # CV + certifs + expériences (croisement « PMP ET bancaire »)
        s.add_all([
            m.KBCvModel(doc_id="cv1", fichier_source="cv_jean.pdf", nom_complet="Jean Kouassi"),
            m.KBCvModel(doc_id="cv2", fichier_source="cv_awa.pdf", nom_complet="Awa Traoré"),
            m.KBCvModel(doc_id="cv3", fichier_source="cv_koffi.pdf", nom_complet="Koffi N'Da"),
            m.KBCvCertificationModel(doc_id="cv1", intitule="PMP"),
            m.KBCvCertificationModel(doc_id="cv2", intitule="PMP"),
            m.KBCvCertificationModel(doc_id="cv3", intitule="ITIL"),
            m.KBCvExperienceModel(doc_id="cv1", secteur="banque"),
            m.KBCvExperienceModel(doc_id="cv2", secteur="telecom"),
            m.KBCvExperienceModel(doc_id="cv3", secteur="banque"),
        ])
        await s.commit()
    # NB : la table `users` existe déjà (créée par Base.metadata.create_all) ; le
    # garde-fou la refuse à la validation, avant toute exécution — pas besoin de la seeder.
    await engine.dispose()


def test_lecture_seule_et_requetes_playbook(tmp_path):
    async def scenario():
        db_file = tmp_path / "kb.db"
        await _seed(db_file)
        ro = ReadOnlySqlAdapter(db_path=db_file, timeout_seconds=5)
        try:
            # 1. Analytique « attestations > 200M »
            r = await ro.query(
                "SELECT COUNT(*) AS n FROM kb_attestation WHERE montant_valeur > 200000000", KB_TABLES)
            assert r["resultats"][0]["n"] == "2"

            # 2. Croisement « PMP ET bancaire » → seul Jean
            r = await ro.query(
                "SELECT DISTINCT cv.nom_complet, cv.doc_id, cv.fichier_source "
                "FROM kb_cv cv "
                "JOIN kb_cv_certifications c ON c.doc_id=cv.doc_id "
                "JOIN kb_cv_experiences e ON e.doc_id=cv.doc_id "
                "WHERE c.intitule LIKE '%PMP%' AND e.secteur LIKE '%banq%'", KB_TABLES)
            noms = [row["nom_complet"] for row in r["resultats"]]
            assert noms == ["Jean Kouassi"]
            # citations disponibles
            assert r["resultats"][0]["fichier_source"] == "cv_jean.pdf"

            # 3. Whitelist : la table sensible `users` est refusée par le garde-fou
            try:
                await ro.query("SELECT email, hashed_password FROM users", KB_TABLES)
                raise AssertionError("users n'aurait pas dû être interrogeable")
            except SqlGuardError:
                pass

            # 4. Écriture bloquée AU NIVEAU CONNEXION (query_only/mode=ro),
            #    même en contournant le garde-fou applicatif.
            wrote = False
            try:
                async with ro._engine.connect() as c:
                    await c.execute(text("CREATE TABLE evil (x INTEGER)"))
                    wrote = True
            except Exception:
                wrote = False
            assert wrote is False, "la connexion lecture seule a accepté une écriture"
        finally:
            await ro.dispose()

    asyncio.run(scenario())
