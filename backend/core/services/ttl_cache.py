"""Cache mémoire TTL générique pour les endpoints d'analyse LLM.

Les endpoints `.../analysis` rappellent Claude à chaque appel (15-20s de
latence avec les prompts enrichis) alors que les chiffres sous-jacents ne
changent qu'au rythme de la sync Odoo (5-10 min, cf. jobs/scheduler.py). Sans
cache, chaque ouverture de page cockpit refait un appel LLM identique — ce
helper évite l'appel répété tant que la fenêtre TTL n'est pas expirée.

Process-local (pas de Redis) : suffisant pour un seul worker uvicorn ; à
remplacer par un cache partagé si le déploiement passe multi-worker.
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

_STORE: dict[tuple, tuple[object, float]] = {}


async def cached(
    key: tuple,
    ttl_seconds: float,
    compute: Callable[[], Awaitable[T]],
    store_if: Callable[[T], bool] | None = None,
) -> T:
    """`store_if` : ne retient le résultat que s'il passe ce test.

    Sans lui, tout résultat occupe la fenêtre — y compris un repli déterministe
    produit pendant une indisponibilité du modèle, ce qui ferait durer un
    incident de quelques secondes pendant tout le TTL (cf.
    uc_arbitrage/narratif.py). Un résultat refusé est renvoyé normalement, il
    n'est simplement pas mémorisé : le prochain appel réessaiera.
    """
    entry = _STORE.get(key)
    if entry is not None and time.monotonic() - entry[1] < ttl_seconds:
        return entry[0]  # type: ignore[return-value]
    result = await compute()
    if store_if is None or store_if(result):
        _STORE[key] = (result, time.monotonic())
    return result
