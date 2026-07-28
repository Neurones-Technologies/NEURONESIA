import asyncio
import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from core.services.ged_indexer import GEDIndexer
from adapters.storage.local_ged_adapter import LocalGEDAdapter, _SUPPORTED_EXT

logger = logging.getLogger(__name__)

_ged_storage = LocalGEDAdapter()

_DEBOUNCE_SEC = 3.0  # Word/PDF génèrent 5-20 events en édition → déduplique


class _GEDEventHandler(FileSystemEventHandler):
    def __init__(self, ged_indexer: GEDIndexer, loop: asyncio.AbstractEventLoop):
        self._indexer = ged_indexer
        self._loop = loop
        self._pending: dict[str, float] = {}  # path → timestamp dernier event

    def _is_supported(self, path: str) -> bool:
        return Path(path).suffix.lower() in _SUPPORTED_EXT

    def _schedule(self, coro):
        """Planifie une coroutine dans la boucle asyncio principale."""
        if self._loop.is_closed():
            logger.warning("GED watcher: event loop fermée, indexation ignorée")
            return
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        fut.add_done_callback(
            lambda f: f.exception() and logger.error("GED watcher coroutine failed: %s", f.exception())
        )

    def on_created(self, event):
        if not event.is_directory and self._is_supported(event.src_path):
            logger.info("GED: nouveau fichier → %s", event.src_path)
            self._debounce(event.src_path, deleted=False)

    def on_modified(self, event):
        if not event.is_directory and self._is_supported(event.src_path):
            self._debounce(event.src_path, deleted=False)

    def on_deleted(self, event):
        if not event.is_directory and self._is_supported(event.src_path):
            logger.info("GED: suppression → %s", event.src_path)
            self._pending.pop(event.src_path, None)
            self._schedule(self._indexer.remove(Path(event.src_path)))

    def _debounce(self, path: str, deleted: bool):
        stamp = time.monotonic()
        self._pending[path] = stamp

        async def _fire():
            await asyncio.sleep(_DEBOUNCE_SEC)
            if self._pending.get(path) != stamp:
                return  # un event plus récent a pris le relais
            self._pending.pop(path, None)
            file_path = Path(path)
            if not file_path.exists():
                return
            doc_type = _ged_storage.infer_doc_type(file_path)
            await self._indexer.process(file_path, doc_type)

        self._schedule(_fire())


class GEDWatcher:
    """Surveille la GED en temps réel et déclenche l'indexation incrémentale."""

    def __init__(self, ged_path: Path, ged_indexer: GEDIndexer):
        self._ged_path = ged_path
        self._ged_indexer = ged_indexer
        self._observer = Observer()
        self._handler: _GEDEventHandler | None = None

    def start(self):
        self._ged_path.mkdir(parents=True, exist_ok=True)
        # Capturer la boucle ICI (dans start(), pas dans __init__) — la boucle est running
        loop = asyncio.get_running_loop()
        self._handler = _GEDEventHandler(self._ged_indexer, loop)
        self._observer.schedule(self._handler, str(self._ged_path), recursive=True)
        self._observer.start()
        logger.info("GED Watcher démarré sur %s (debounce %ss)", self._ged_path, _DEBOUNCE_SEC)

    def stop(self):
        self._observer.stop()
        self._observer.join()
        logger.info("GED Watcher arrêté")
