import logging

from adapters.storage.local_ged_adapter import LocalGEDAdapter, _TYPE_MAP
from core.services.ged_indexer import GEDIndexer

logger = logging.getLogger(__name__)


async def run_ged_scan(ged_indexer: GEDIndexer):
    """
    Scan nocturne de la GED — fallback au cas où watchdog aurait raté un fichier.
    Compare les hash et re-indexe uniquement les fichiers modifiés.
    """
    logger.info("Scan GED nocturne démarré")
    storage = LocalGEDAdapter()
    indexed = 0
    skipped = 0

    for folder_name, doc_type in _TYPE_MAP.items():
        files = storage.list_files(doc_type)
        for file_path in files:
            try:
                was_indexed = await ged_indexer.process(file_path, doc_type)
                if was_indexed:
                    indexed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error("Erreur scan GED [%s]: %s", file_path.name, e)

    logger.info("Scan GED terminé : %d indexés, %d inchangés", indexed, skipped)
