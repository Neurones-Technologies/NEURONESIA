import logging
from datetime import datetime

from sqlalchemy import delete, select

from db.database import AsyncSessionLocal
from db.models import BacklogSnapshotModel, DossierModel, OpportunityModel, PipelineSnapshotModel

logger = logging.getLogger(__name__)


async def run_pipeline_snapshot() -> None:
    """Capture l'état du jour de `opportunities` et `dossiers` dans des tables
    append-only. Idempotent : un rerun le même jour remplace les lignes du jour
    plutôt que de les dupliquer."""
    snapshot_date = datetime.utcnow().date()

    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(PipelineSnapshotModel).where(PipelineSnapshotModel.snapshot_date == snapshot_date)
        )
        await session.execute(
            delete(BacklogSnapshotModel).where(BacklogSnapshotModel.snapshot_date == snapshot_date)
        )

        opportunities = (await session.execute(select(OpportunityModel))).scalars().all()
        for opp in opportunities:
            session.add(PipelineSnapshotModel(
                snapshot_date=snapshot_date,
                opp_id=opp.opp_id,
                odoo_id=opp.odoo_id,
                client_id=opp.client_id,
                client_name=opp.client_name,
                name=opp.name,
                stage=opp.stage,
                expected_revenue=opp.expected_revenue,
                probability=opp.probability,
                salesperson_name=opp.salesperson_name,
                deadline=opp.deadline,
                created_at=opp.created_at,
            ))

        dossiers = (await session.execute(select(DossierModel))).scalars().all()
        for dossier in dossiers:
            session.add(BacklogSnapshotModel(
                snapshot_date=snapshot_date,
                dossier_ref=dossier.dossier_ref,
                client_name=dossier.client_name,
                salesperson=dossier.salesperson,
                state=dossier.state,
                backlog=dossier.backlog,
                ca_provisoire=dossier.ca_provisoire,
                ca_definitif=dossier.ca_definitif,
                marge_definitive=dossier.marge_definitive,
                montant_recu=dossier.montant_recu,
                reste_a_encaisser=dossier.reste_a_encaisser,
            ))

        await session.commit()
        logger.info(
            "Snapshot pipeline/backlog du %s : %d opportunités, %d dossiers",
            snapshot_date, len(opportunities), len(dossiers),
        )
