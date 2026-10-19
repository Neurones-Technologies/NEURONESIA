"""Date de bascule du pipeline d'Odoo vers nt360.

Le pipeline est un STOCK : il ne se lit dans le passé qu'à travers les
`pipeline_snapshots`, photographiés chaque nuit depuis `opportunities` (Odoo)
puis depuis v_opportunities (nt360). Les deux univers ne se recouvrent pas :
nt360 a écarté 1 230 opportunités Odoo (perdues, suspendues, annulées…) et en
porte 1 864 gagnées qu'Odoo n'a pas. Comparer une photo d'avant la bascule à
une photo d'après fabriquerait des mouvements qui n'ont jamais eu lieu
(« 1 230 opportunités disparues », pipeline en chute de 50 Md).

Contrairement aux flux (cf. indicateurs.rebaser), un stock ne se recalcule pas
après coup. On n'efface donc rien : on DATE la bascule, et toute comparaison de
snapshots refuse de la traverser — le delta du pipeline est « non disponible »
quelques jours, plutôt que faux.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import delete

from config.settings import settings
from db.database import AsyncSessionLocal
from db.models import IndicatorSnapshotModel

logger = logging.getLogger(__name__)

_FICHIER = settings.local_db_path.parent / "bascule_nt360.json"


def date_opportunites() -> date | None:
    """Premier jour dont les snapshots de pipeline viennent de nt360, ou None
    tant que la bascule n'a pas eu lieu (aucune coupure à appliquer)."""
    try:
        brut = json.loads(_FICHIER.read_text()).get("opportunites")
        return date.fromisoformat(brut) if brut else None
    except (OSError, ValueError):
        return None


async def basculer_opportunites() -> date | None:
    """Date la bascule, une seule fois. Rend la date posée, None si déjà faite.

    1. Reprend le snapshot du jour : celui de 1h00 a photographié Odoo, il est
       remplacé par une photo nt360 (le job est idempotent sur la journée).
    2. Efface les valeurs d'indicateurs de pipeline du jour, calculées sur la
       photo Odoo — le delta les recalculera à la volée sur la nouvelle.
    3. Pose la date : rien d'antérieur ne sera plus comparé au pipeline nt360.
    """
    if date_opportunites() is not None:
        return None
    from jobs.pipeline_snapshot_job import run_pipeline_snapshot
    from modules.uc_briefing import indicateurs

    await run_pipeline_snapshot()
    jour = datetime.utcnow().date()      # même horloge que run_pipeline_snapshot
    cles_pipe = [c for c, ind in indicateurs.CATALOGUE.items() if ind.source_snapshot == "pipeline_snapshots"]
    async with AsyncSessionLocal() as session:
        await session.execute(delete(IndicatorSnapshotModel).where(
            IndicatorSnapshotModel.cle.in_(cles_pipe), IndicatorSnapshotModel.snapshot_date >= jour))
        await session.commit()
    _FICHIER.parent.mkdir(parents=True, exist_ok=True)
    _FICHIER.write_text(json.dumps({"opportunites": jour.isoformat(), "le": datetime.utcnow().isoformat()}))
    indicateurs.vider_cache_snapshots()
    logger.info("Pipeline basculé sur nt360 : snapshots comparables à partir du %s", jour)
    return jour
