import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.services.ged_indexer import GEDIndexer
from core.ports.crm_repository import CRMRepository
from modules.uc_arbitrage import narration_store

logger = logging.getLogger(__name__)


def build_scheduler(
    ged_indexer: GEDIndexer,
    crm_repo: CRMRepository,
    odoo_sync_interval_hours: int = 2,
    container=None,
) -> AsyncIOScheduler:
    from config.settings import settings
    scheduler = AsyncIOScheduler()

    # Sync Odoo : min 5 min, max 1 instance, coalesce pour éviter pile-up
    sync_interval = max(5, settings.odoo_sync_interval_minutes)
    scheduler.add_job(
        _sync_odoo_job,
        trigger=IntervalTrigger(minutes=sync_interval),
        id="odoo_sync",
        name="Sync Odoo → SQLite local",
        replace_existing=True,
        misfire_grace_time=120,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        _scan_ged_job,
        args=[ged_indexer],
        trigger=CronTrigger(hour=2, minute=0),
        id="ged_scan",
        name="Scan GED nocturne",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        _reset_monthly_budget,
        trigger=CronTrigger(day=1, hour=0, minute=0),
        id="budget_reset",
        name="Reset budget tokens mensuel",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        _quarantine_purge_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="quarantine_purge",
        name="Purge quarantaine (fichiers non indexables)",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        _daily_briefing_job,
        args=[container],
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_briefing",
        name="Briefing quotidien par rôle (analyses IA figées jusqu'au lendemain minuit)",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        _pipeline_snapshot_job,
        trigger=CronTrigger(hour=1, minute=0),
        id="pipeline_snapshot",
        name="Snapshot quotidien pipeline/backlog (append-only, moteurs M3/M5)",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    # 1h15 — APRÈS le snapshot d'objets de 1h00, jamais avant : les indicateurs de
    # stock (pipe, backlog) se reconstituent depuis `pipeline_snapshots` et
    # `backlog_snapshots`. Lancé en premier, ce job laisserait un trou d'une
    # journée dans les seules séries qui ne sont pas recalculables après coup.
    scheduler.add_job(
        _indicator_snapshot_job,
        trigger=CronTrigger(hour=1, minute=15),
        id="indicator_snapshot",
        name="Historisation des indicateurs du briefing (socle des deltas)",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    # 6h00 : après plusieurs sync Odoo de la nuit et du petit matin, donc sur des
    # chiffres frais, et avant l'arrivée des utilisateurs — ils trouvent les
    # narrations déjà écrites au lieu d'un squelette de 10 à 20 s.
    scheduler.add_job(
        _daily_analyses_job,
        args=[container],
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_analyses",
        name="Analyses IA quotidiennes du cockpit (7 sections, figées en base)",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True,
        max_instances=1,
    )

    # Les rédactions d'arbitrage sont invalidées par le CONTENU (empreinte du
    # dossier), pas par une horloge : une ligne périmée n'est jamais relue mais
    # reste en base. Sans cette purge, la table grossit au rythme des sync Odoo
    # qui déplacent un montant cité.
    scheduler.add_job(
        _arbitrage_narration_purge_job,
        trigger=CronTrigger(hour=3, minute=45),
        id="arbitrage_narration_purge",
        name="Purge des rédactions d'arbitrage périmées",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True,
        max_instances=1,
    )

    logger.info(
        "Scheduler configuré : sync Odoo toutes les %d min (coalesce, max 1), scan GED à 2h00, "
        "purge quarantaine à 3h30 (rétention %d j), purge rédactions d'arbitrage à 3h45 "
        "(rétention %d j), briefing quotidien à 0h00, snapshot pipeline/backlog à 1h00, "
        "historisation des indicateurs à 1h15, analyses IA du cockpit à 6h00",
        sync_interval, settings.quarantine_retention_days, narration_store.RETENTION_JOURS,
    )
    return scheduler


async def _sync_odoo_job():
    from jobs.odoo_sync_job import run_odoo_sync
    await run_odoo_sync()


async def _scan_ged_job(ged_indexer: GEDIndexer):
    from jobs.ged_scan_job import run_ged_scan
    await run_ged_scan(ged_indexer)


async def _reset_monthly_budget():
    logger.info("Reset budget tokens mensuel")


async def _daily_briefing_job(container=None):
    """Régénère le briefing quotidien (5 rôles) — gelé jusqu'à ce run demain minuit."""
    from modules.uc_briefing import service
    if container is None:
        logger.warning("Briefing quotidien — container absent, run ignoré")
        return
    llm = getattr(container, "llm_sonnet", None)
    await service.generate(container.crm_repo, llm, triggered_by="schedule")


async def _daily_analyses_job(container=None):
    """Régénère les 7 narrations IA du cockpit — gelées en base jusqu'au run de
    demain matin (cf. modules/uc_daily_analysis/store.py)."""
    from modules.uc_daily_analysis import service
    if container is None:
        logger.warning("Analyses IA quotidiennes — container absent, run ignoré")
        return
    llm = getattr(container, "llm_sonnet", None)
    await service.generate_all(container.crm_repo, llm, triggered_by="schedule")


async def _quarantine_purge_job():
    """Supprime les fichiers en quarantaine depuis trop longtemps (non indexables)."""
    from pathlib import Path
    from config.settings import settings
    from adapters.registry.quarantine_adapter import QuarantineAdapter

    paths = await QuarantineAdapter().purge_expired(settings.quarantine_retention_days)
    removed = 0
    for p in paths:
        try:
            fp = Path(p)
            if fp.exists():
                fp.unlink()
                removed += 1
        except OSError as e:
            logger.warning("Purge quarantaine — suppression %s impossible : %s", p, e)
    if paths:
        logger.info("Purge quarantaine : %d entrée(s) périmée(s), %d fichier(s) supprimé(s)", len(paths), removed)


async def _arbitrage_narration_purge_job():
    """Supprime les rédactions d'arbitrage devenues inatteignables (cf.
    modules/uc_arbitrage/narration_store.py)."""
    purgees = await narration_store.purge_anciennes()
    if purgees:
        logger.info("Purge rédactions d'arbitrage : %d ligne(s) périmée(s)", purgees)


async def _pipeline_snapshot_job():
    from jobs.pipeline_snapshot_job import run_pipeline_snapshot
    await run_pipeline_snapshot()


async def _indicator_snapshot_job():
    from jobs.indicator_snapshot_job import run_indicator_snapshot
    await run_indicator_snapshot()
