"""Historisation quotidienne des indicateurs du briefing.

Distinct de `pipeline_snapshot_job`, qui capture des OBJETS (une ligne par
opportunité, une par dossier). Celui-ci capture des VALEURS déjà agrégées : sans
elles, afficher « +85 M vs hier » supposerait de rejouer chaque nuit toutes les
agrégations de tous les rôles sur tout l'historique.

Ordre imposé dans le scheduler : ce job passe APRÈS `pipeline_snapshot`, parce
que les indicateurs de stock (pipe, backlog) lisent le snapshot d'objets du jour
lorsqu'ils sont reconstitués. L'inverse laisserait un trou d'une journée.

Le premier démarrage déclenche une RECONSTITUTION sur `FENETRE_AMORCAGE_JOURS` :
les flux se recalculent depuis les dates portées par les faits, si bien que le
delta est disponible dès le premier matin au lieu du trente-et-unième.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func, select

from db.database import AsyncSessionLocal
from db.models import IndicatorSnapshotModel
from modules.uc_briefing import indicateurs

logger = logging.getLogger(__name__)

# Profondeur reconstituée au premier passage. 400 jours : assez pour couvrir la
# comparaison à l'exercice précédent à date comparable, qui est la seule
# comparaison de fond du briefing DG.
FENETRE_AMORCAGE_JOURS = 400


async def run_indicator_snapshot(jour: date | None = None) -> dict:
    """Mesure les indicateurs du jour, et amorce l'historique au premier passage.

    Idempotent : un rerun le même jour remplace les valeurs du jour plutôt que de
    les dupliquer (même contrat que `run_pipeline_snapshot`).
    """
    jour = jour or date.today()
    indicateurs.vider_cache_snapshots()

    async with AsyncSessionLocal() as session:
        deja = (await session.execute(
            select(func.count()).select_from(IndicatorSnapshotModel)
        )).scalar() or 0

    amorce = None
    if not deja:
        depuis = jour - timedelta(days=FENETRE_AMORCAGE_JOURS)
        logger.info(
            "Première historisation des indicateurs : reconstitution du %s au %s "
            "(les flux se recalculent depuis les dates portées par les faits)",
            depuis, jour,
        )
        amorce = await indicateurs.reconstituer(depuis, jour)

    valeurs = await indicateurs.capturer_jour(jour)
    logger.info(
        "Indicateurs du %s : %d valeurs mesurées sur %d au catalogue",
        jour, len(valeurs), len(indicateurs.CATALOGUE),
    )
    return {"jour": jour.isoformat(), "mesures": len(valeurs), "amorcage": amorce}


async def run_indicator_backfill(depuis: date, jusqu_a: date | None = None) -> dict:
    """Reconstitution explicite d'une fenêtre — après correction d'une requête,
    ou pour rattraper une interruption du job de nuit."""
    return await indicateurs.reconstituer(depuis, jusqu_a)
