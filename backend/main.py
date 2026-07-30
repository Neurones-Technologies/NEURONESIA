import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config.rate_limit import limiter
from config.settings import settings
from config.container import Container
from db.database import init_db
from api.v1 import health, chat, stats, crm, webhooks, ged, auth, dashboard, insights
from api.v1.dependencies import get_current_user, require_views
from modules.uc_arbitrage.router import router as arbitrage_router
from modules.uc_briefing.router import router as briefing_router
from modules.uc_clients.router import router as clients_router
from modules.uc_crosssell.router import router as crosssell_router
from modules.uc_partners.router import router as partners_router

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


_DEFAULT_SECRET_KEY = "change-me-in-production-use-openssl-rand-hex-32"


def _refuse_insecure_secret_in_prod() -> None:
    """Refuse de démarrer en environnement non-dev avec la clé JWT par défaut
    codée en dur (`config/settings.py`) — sinon tout token est forgeable par
    quiconque lit le code source. Mieux vaut un crash au démarrage, explicite
    et immédiat, qu'une exposition silencieuse en production."""
    if settings.app_env != "development" and settings.secret_key == _DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY par défaut détectée en environnement non-dev "
            f"(APP_ENV={settings.app_env!r}). Renseigne un SECRET_KEY réel "
            "(ex. `openssl rand -hex 32`) dans backend/.env.prod avant de démarrer."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _refuse_insecure_secret_in_prod()
    logger.info("Démarrage Neurones IA v%s [%s]", settings.app_version, settings.app_env)
    await init_db()
    container = Container()
    await container.startup()
    app.state.container = container
    yield
    logger.info("Arrêt Neurones IA")
    await container.shutdown()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env == "development" else None,
)

_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]

# Rate-limiting (slowapi) — protège /auth/login (voir décorateur sur l'endpoint)
# du brute-force/credential stuffing, qui n'avait jusqu'ici aucune friction.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# GZip pour toutes les réponses JSON > 1 Ko (exclut SSE — Content-Encoding incompatible)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_auth = [Depends(get_current_user)]

# Endpoints publics (pas de token requis)
app.include_router(health.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")

# Endpoints protégés
app.include_router(chat.router, prefix="/v1", dependencies=_auth)
app.include_router(stats.router, prefix="/v1", dependencies=_auth)
app.include_router(dashboard.router, prefix="/v1", dependencies=_auth)
app.include_router(insights.router, prefix="/v1", dependencies=_auth)
app.include_router(crm.router, prefix="/v1", dependencies=_auth)
app.include_router(ged.router, prefix="/v1", dependencies=_auth)
# Briefing quotidien : gated par la matrice module × rôle (vue "briefing")
app.include_router(briefing_router, prefix="/v1", dependencies=[Depends(require_views("briefing"))])
# Montée en valeur : gated par la matrice module × rôle (vue "crosssell")
app.include_router(crosssell_router, prefix="/v1", dependencies=[Depends(require_views("crosssell"))])
# Portefeuille clients : gated par la matrice module × rôle (vues "clients"/"portefeuille")
app.include_router(clients_router, prefix="/v1", dependencies=[Depends(require_views("clients", "portefeuille"))])
# Fournisseurs : gated par la matrice module × rôle (vues "partenaires"/"portefeuille")
app.include_router(partners_router, prefix="/v1", dependencies=[Depends(require_views("partenaires", "portefeuille"))])
# Arbitrages : gated par la matrice module × rôle (vue "arbitrage")
app.include_router(arbitrage_router, prefix="/v1", dependencies=[Depends(require_views("arbitrage"))])

# Webhooks Odoo : protégés par HMAC secret séparé (pas JWT)
app.include_router(webhooks.router, prefix="/v1")
