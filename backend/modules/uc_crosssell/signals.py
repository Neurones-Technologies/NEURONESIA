"""Signaux de montée en valeur, lecture partagée et mise en cache.

Le calcul complet coûte deux postes fixes : une lecture SQL des ~19 500 lignes
de commande du miroir (~100 ms), puis leur classement en Python par
`build_montee_valeur` (~190 ms de CPU — pendant lesquelles la boucle
d'événements ne sert aucune autre requête, tous modules confondus).

Quatre consommateurs demandent exactement le même résultat : l'écran montée en
valeur, son analyse LLM, le fil d'actions prioritaires du dashboard et la file
d'arbitrage. Chacun le recalculait pour lui seul à chaque requête, alors que les
lignes de commande ne changent qu'au rythme de la sync Odoo
(`jobs/scheduler.py`, au minimum toutes les 5 min).

Le calcul n'est pas rétréci (pas de filtre par client en amont) parce qu'il ne
le supporte pas : `build_montee_valeur` tronque chaque liste à un top 20 calculé
sur l'ensemble des clients, donc lire moins de lignes changerait les signaux
retenus au lieu de simplement les produire plus vite.

Le résultat est PARTAGÉ entre requêtes : ses appelants le lisent sans jamais le
modifier (ils recopient les éléments dont ils ont besoin).
"""
from __future__ import annotations

import asyncio

from core.services.ttl_cache import cached
from modules.uc_crosssell.aggregation import build_montee_valeur

# Sous le pas de sync Odoo, pour qu'une sync soit toujours visible au tour suivant.
_TTL_SECONDES = 120.0
_CACHE_KEY = ("crosssell_signaux",)


async def get_signals(crm) -> dict:
    """Signaux montée en valeur (renouvellement / obsolescence / cross-sell /
    up-sell) calculés sur les vraies lignes de commande."""

    async def _compute() -> dict:
        lines = await crm.get_order_lines()
        # `build_montee_valeur` est du CPU pur et non négligeable (~190 ms sur le
        # miroir courant, un `_classify` par ligne sur ~19 500 lignes). L'exécuter
        # dans la boucle d'événements gelait tout le serveur pendant ce temps —
        # y compris les requêtes des autres modules. Un thread le sort du chemin
        # critique, et laisse les lectures SQL concurrentes progresser pendant
        # qu'il tourne (le classement ne touche à aucun état partagé).
        return await asyncio.to_thread(build_montee_valeur, lines)

    return await cached(_CACHE_KEY, _TTL_SECONDES, _compute)
