"""
Outils de latence du module Présale (UC10) — ISOLÉS.

Trois leviers, sans toucher aux adapters LLM partagés ni aux autres modules :
  • `timer(label)`     : chrono d'une grande étape, loggé si `presales_perf_log` (« Lot 0 »
                         de mesure : on optimise sur des faits, pas des estimations) ;
  • `with_timeout(...)`: timeout DUR optionnel d'un appel LLM (asyncio.wait_for) — un appel
                         qui traîne est coupé proprement au lieu de bloquer toute la requête ;
  • `prune_cache_dir`  : purge LRU d'un dossier de cache disque (garde les N plus récents),
                         ce qui rend la réactivation des caches sûre en prod.

Dépend uniquement de la stdlib + `settings`. Logique pure → testable hors réseau.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import contextmanager
from pathlib import Path

from config.settings import settings

logger = logging.getLogger("uc10_presales.latency")


@contextmanager
def timer(label: str):
    """Mesure la durée du bloc et la logge (si `presales_perf_log`).

    Usage : `with timer("score_ao"): result = await ...`. N'avale aucune exception
    et n'altère pas le résultat — purement observationnel.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        if settings.presales_perf_log:
            elapsed = time.perf_counter() - start
            logger.info("[perf] %s : %.2f s", label, elapsed)


async def with_timeout(coro, label: str, seconds: float | None = None):
    """Exécute `coro` avec un timeout dur optionnel.

    `seconds=None` → `settings.presales_llm_timeout_seconds`. ≤ 0 → aucun timeout
    (await direct, comportement historique). En cas de dépassement, logge et relève
    `asyncio.TimeoutError` (l'appelant décide de dégrader ou de remonter l'erreur).
    """
    limit = settings.presales_llm_timeout_seconds if seconds is None else seconds
    if not limit or limit <= 0:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout=limit)
    except asyncio.TimeoutError:
        logger.warning("[perf] %s : TIMEOUT au-delà de %.0f s — appel coupé.", label, limit)
        raise


def content_key(*parts: object) -> str:
    """Empreinte SHA-256 stable d'un ensemble de parties → clé de cache content-addressée.

    Les parties sont jointes par un séparateur improbable ; `None` devient "". Sert à
    mémoriser stratégie/offre par contenu (même entrée → même clé → même résultat).
    """
    joined = "␟".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def prune_cache_dir(directory: Path, max_files: int, *, suffix: str = ".json") -> int:
    """Purge LRU : ne conserve que les `max_files` fichiers `*suffix` les plus récents.

    `max_files <= 0` → no-op (purge désactivée). Renvoie le nombre de fichiers supprimés.
    Jamais d'exception fatale : une erreur de suppression est ignorée (best effort).
    """
    if max_files is None or max_files <= 0:
        return 0
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    files = [p for p in directory.glob(f"*{suffix}") if p.is_file()]
    if len(files) <= max_files:
        return 0
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)  # plus récents d'abord
    deleted = 0
    for path in files[max_files:]:
        try:
            path.unlink()
            deleted += 1
        except OSError:
            pass
    if deleted:
        logger.info("[cache] purge LRU de %s : %d fichiers supprimés (garde %d)",
                    directory.name, deleted, max_files)
    return deleted
