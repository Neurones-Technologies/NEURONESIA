"""Situation des factures échues, hors couche HTTP.

Le débrief quotidien du DG (uc_briefing.facts) consomme ce point d'entrée
comme il consomme la file d'arbitrage : un module voisin appelable depuis un
job sans contexte FastAPI. Le calcul lui-même vit dans
`relation_commerciale.situation_factures`, sur les MÊMES fonctions que
l'écran Relation commerciale du DAF — jamais deux chiffrages du même sujet.
"""
import asyncio
from datetime import date

from modules.uc_daf import queries as q
from modules.uc_daf import relation_commerciale


async def situation_factures() -> dict:
    """Stock échu clients/fournisseurs. Cf. relation_commerciale.situation_factures."""
    factures_clients, factures_fournisseurs = await asyncio.gather(
        q.fetch_factures_clients(), q.fetch_factures_fournisseurs()
    )
    # Boucles Python pures sur ~6 600 lignes : hors de la boucle d'événements,
    # même arbitrage que uc_daf/router._hors_boucle.
    return await asyncio.to_thread(
        relation_commerciale.situation_factures,
        factures_clients, factures_fournisseurs, date.today(),
    )
