"""Test de montée en charge du cockpit (endpoints de lecture).

Lancement (depuis backend/) :
    .venv/Scripts/python.exe -m locust -f tests/load/locustfile.py --host http://localhost:8000

Mode non-interactif (palier unique) :
    .venv/Scripts/python.exe -m locust -f tests/load/locustfile.py \
        --host http://localhost:8000 --headless -u 50 -r 5 -t 2m

PÉRIMÈTRE — uniquement des GET de lecture. Les POST `.../analysis` sont
volontairement EXCLUS : ils appellent le LLM (coût réel en tokens) et sont
figés par un cache journalier (modules/uc_daily_analysis/store.py), donc ils
mesureraient le cache, pas le service.

IDENTIFIANTS — LOAD_TEST_EMAIL / LOAD_TEST_PASSWORD. Le mot de passe n'a PAS
de valeur par défaut (rien de secret dans le dépôt) : sans lui, le run s'arrête
au premier login avec la marche à suivre.

AUTHENTIFICATION — un SEUL login pour tout le run, partagé par tous les
utilisateurs virtuels. Deux raisons :
  - `/auth/login` est rate-limité à 5/minute par IP (config/rate_limit.py) ;
    un login par utilisateur virtuel ne produirait que des 429.
  - le hash bcrypt (cost 12) coûte ~1,2 s ; se relogger mesurerait bcrypt
    plutôt que les endpoints visés.
"""
import os

import gevent
from locust import HttpUser, between, task

EMAIL = os.environ.get("LOAD_TEST_EMAIL", "oboyer@neuronestech.com")
# Aucune valeur par defaut : un mot de passe code dans le depot est un mot de
# passe public. Absent, le run echoue au premier login avec la marche a suivre
# (cf. _fetch_token) plutot que sur un 401 opaque.
PASSWORD = os.environ.get("LOAD_TEST_PASSWORD", "")

# Token partagé par tous les utilisateurs virtuels, obtenu UNE seule fois.
#
# Le login se fait paresseusement (au démarrage du premier utilisateur) et non
# dans un listener `test_start` : l'horloge de `--run-time` démarre à
# l'initialisation du process, donc un login bloquant de ~3 s y était décompté
# et, sur un run court, tout le budget passait dans l'authentification avant
# qu'une seule requête ne soit émise.
_TOKEN: str | None = None
_TOKEN_ERROR: str | None = None
_TOKEN_LOCK = gevent.lock.Semaphore()


def _fetch_token(user: HttpUser) -> str:
    """Retourne le token partagé, en le demandant au besoin.

    Le sémaphore garantit un seul appel à `/auth/login` même si N utilisateurs
    démarrent simultanément — indispensable car l'endpoint est rate-limité à
    5/minute par IP (config/rate_limit.py) et coûte ~3 s (bcrypt cost 12).
    """
    global _TOKEN, _TOKEN_ERROR

    with _TOKEN_LOCK:
        if _TOKEN:
            return _TOKEN
        if _TOKEN_ERROR:
            raise RuntimeError(_TOKEN_ERROR)

        if not PASSWORD:
            _TOKEN_ERROR = (
                "LOAD_TEST_PASSWORD absente — exporte le mot de passe du compte "
                f"{EMAIL} (celui utilise au seed, cf. scripts/seed_demo_users.py) "
                "avant de lancer locust."
            )
            raise RuntimeError(_TOKEN_ERROR)

        # `catch_response` : le login est une amorce du test, pas une mesure —
        # on ne veut pas ses ~3 s de bcrypt dans les statistiques des endpoints.
        with user.client.post(
            "/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            name="[setup] login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                _TOKEN_ERROR = (
                    f"Login impossible ({response.status_code}) pour {EMAIL} — "
                    f"réponse : {response.text[:200]}"
                )
                response.failure(_TOKEN_ERROR)
                raise RuntimeError(_TOKEN_ERROR)
            response.success()
            _TOKEN = response.json()["access_token"]

        print(f"[load] Token obtenu pour {EMAIL}")
        return _TOKEN


class CockpitReader(HttpUser):
    """Simule un utilisateur consultant les écrans du cockpit.

    `between(1, 3)` — temps de réflexion entre deux écrans. Sans pause, on
    mesurerait un débit maximal théorique que personne ne produit ; avec, la
    charge ressemble à N utilisateurs réels naviguant dans l'application.
    """

    wait_time = between(1, 3)

    def on_start(self):
        self.client.headers["Authorization"] = f"Bearer {_fetch_token(self)}"

    # Poids proportionnels à l'usage attendu : le tableau de bord est l'écran
    # d'accueil, donc le plus sollicité.

    @task(10)
    def kpis(self):
        self.client.get("/v1/dashboard/kpis", name="/dashboard/kpis")

    @task(4)
    def monthly_revenue(self):
        self.client.get("/v1/dashboard/monthly-revenue", name="/dashboard/monthly-revenue")

    @task(4)
    def top_clients(self):
        self.client.get("/v1/dashboard/top-clients", name="/dashboard/top-clients")

    @task(3)
    def revenue_by_sector(self):
        self.client.get("/v1/dashboard/revenue/by-sector", name="/dashboard/revenue/by-sector")

    @task(3)
    def margins(self):
        self.client.get("/v1/dashboard/margins", name="/dashboard/margins")

    @task(3)
    def forecast(self):
        self.client.get("/v1/dashboard/forecast", name="/dashboard/forecast")

    @task(2)
    def unpaid(self):
        self.client.get("/v1/dashboard/unpaid", name="/dashboard/unpaid")

    @task(2)
    def dso(self):
        self.client.get("/v1/dashboard/dso", name="/dashboard/dso")

    @task(2)
    def next_actions(self):
        self.client.get("/v1/dashboard/next-actions", name="/dashboard/next-actions")

    # `offer-mix` est documenté comme le point lent du cockpit (~318 ms de
    # boucles Python recalculées à chaque affichage, cf. dashboard.py) — gardé
    # dans le scénario précisément pour observer sa dégradation sous charge.
    @task(2)
    def offer_mix(self):
        self.client.get("/v1/dashboard/offer-mix", name="/dashboard/offer-mix")

    @task(1)
    def health(self):
        self.client.get("/v1/health", name="/health")
