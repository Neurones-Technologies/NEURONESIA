"""Limiter partagé (slowapi) — module séparé pour éviter tout import circulaire
entre `main.py` (qui l'enregistre comme middleware) et les routers (qui
l'utilisent comme décorateur sur des endpoints sensibles, ex. `/auth/login`).

LIMITE CONNUE : stockage en mémoire (par processus). Le backend tourne avec
`--workers 2` (Dockerfile) — chaque worker a son propre compteur, donc un
seuil "N/minute" devient en pratique jusqu'à N×workers/minute au total.
Les limites posées sur les endpoints (ex. `/auth/login`) sont divisées en
conséquence pour rester honnêtes sur le plafond RÉEL. Si un Redis est un
jour déployé (`REDIS_URL` existe déjà dans settings.py mais aucun service
Redis n'est présent dans docker-compose.yml/.local.yml à ce jour), passer
`storage_uri=settings.redis_url` ici rendrait le comptage exact, partagé
entre workers.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
