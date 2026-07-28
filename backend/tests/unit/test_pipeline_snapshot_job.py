import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import jobs.pipeline_snapshot_job as pipeline_snapshot_job
from db.database import Base
from db.models import BacklogSnapshotModel, DossierModel, OpportunityModel, PipelineSnapshotModel


async def _seed(session_factory):
    async with session_factory() as session:
        session.add_all([
            OpportunityModel(
                opp_id="opp_1", odoo_id=1, client_id="1", client_name="CIE",
                name="Renouvellement parc", stage="Proposition", expected_revenue=1000.0,
                probability=60.0, salesperson_name="Assamoi",
            ),
            OpportunityModel(
                opp_id="opp_2", odoo_id=2, client_id="2", client_name="SGCI",
                name="TMA infra", stage="Négociation", expected_revenue=500.0,
                probability=80.0, salesperson_name="Diallo",
            ),
            DossierModel(
                dossier_ref="DC/2026/0001", odoo_id=10, client_name="CIE", state="confirmed",
                backlog=200.0, ca_provisoire=800.0, ca_definitif=600.0,
                marge_definitive=120.0, montant_recu=400.0, reste_a_encaisser=200.0,
            ),
            DossierModel(
                dossier_ref="DC/2026/0002", odoo_id=11, client_name="SGCI", state="draft",
                backlog=50.0, ca_provisoire=100.0,
            ),
        ])
        await session.commit()


async def _run_scenario(runs: int):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    await _seed(session_factory)

    original_factory = pipeline_snapshot_job.AsyncSessionLocal
    pipeline_snapshot_job.AsyncSessionLocal = session_factory
    try:
        for _ in range(runs):
            await pipeline_snapshot_job.run_pipeline_snapshot()
    finally:
        pipeline_snapshot_job.AsyncSessionLocal = original_factory

    async with session_factory() as session:
        pipeline_rows = (await session.execute(select(PipelineSnapshotModel))).scalars().all()
        backlog_rows = (await session.execute(select(BacklogSnapshotModel))).scalars().all()

    await engine.dispose()
    return pipeline_rows, backlog_rows


def test_run_pipeline_snapshot_capture_etat_du_jour():
    pipeline_rows, backlog_rows = asyncio.run(_run_scenario(runs=1))

    assert len(pipeline_rows) == 2
    assert len(backlog_rows) == 2
    assert {r.snapshot_date for r in pipeline_rows} == {datetime.utcnow().date()}

    cie = next(r for r in pipeline_rows if r.opp_id == "opp_1")
    assert cie.expected_revenue == 1000.0
    assert cie.probability == 60.0
    assert cie.client_name == "CIE"

    dossier_cie = next(r for r in backlog_rows if r.dossier_ref == "DC/2026/0001")
    assert dossier_cie.backlog == 200.0
    assert dossier_cie.ca_definitif == 600.0


def test_run_pipeline_snapshot_idempotent_meme_jour():
    """Un rerun le même jour ne doit pas dupliquer les lignes (delete-puis-insert)."""
    pipeline_rows, backlog_rows = asyncio.run(_run_scenario(runs=2))

    assert len(pipeline_rows) == 2
    assert len(backlog_rows) == 2
