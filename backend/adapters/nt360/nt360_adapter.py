"""Client lecture seule de l'API nt360 v1 (Neurones Technologies).

nt360 est une source COMPLÉMENTAIRE à Odoo, pas un CRM interchangeable : il ne
porte ni lignes de commande, ni marge réalisée. D'où l'absence de port dans
`core/ports` — seul le job de synchro nt360 consomme cet adapter, comme
OdooAdapter n'est consommé que par la synchro Odoo.

Trois comportements de l'API, constatés au sondage du 2026-10-19 et non tous
documentés, commandent la forme de ce client :

1. PAGINATION. Une page peut contenir moins d'éléments que `limit` sans être la
   dernière (factures : 3 éléments pour limit=5, avec une suite) : seule
   `suite: null` signale la fin.
2. TRONCATURE MUETTE. `opportunities` et `accounts` ne renvoient jamais `suite` :
   une liste qui atteint exactement `limit` est donc probablement coupée, sans
   que l'API le dise (stage 6 = 500 pile). `fetch_all` le signale par
   `complete=False` au lieu de laisser croire à une liste entière.
3. ENCODAGE. Les messages d'erreur arrivent en UTF-8 sans charset déclaré
   (« cl� API invalide ») : le corps est décodé explicitement en UTF-8.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable
from urllib.parse import quote

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

PAGE_MAX = 500          # plafond documenté de `limit`
_MAX_PAGES = 1000       # garde-fou contre un curseur qui ne finirait jamais
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 60.0
# Quota documenté : 600 requêtes/minute/clé. 9 req/s (540/min) laisse une marge.
# Sans ce pas, la relecture unitaire des opportunités (≈ 3 000 GET, 5 en
# parallèle) a déclenché des 429 en rafale au premier essai réel.
_INTERVALLE_MIN_S = 1 / 9


class Nt360Error(RuntimeError):
    """Erreur nt360 après épuisement des nouvelles tentatives."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class Nt360AuthError(Nt360Error):
    """401/403 : clé absente, révoquée ou sans le droit requis. Jamais retentée."""


@dataclass
class Nt360Liste:
    """Résultat d'une lecture complète d'une ressource.

    `complete=False` : la liste est probablement tronquée (ressource sans
    pagination dont la réponse atteint `limit`) ou interrompue par le garde-fou
    de pages. Le job de synchro ne doit alors pas en déduire de suppressions.
    """
    items: list[dict] = field(default_factory=list)
    pages: int = 0
    complete: bool = True


class Nt360Adapter:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        max_retries: int = 5,
        timeout: float = 60.0,
        intervalle_min_s: float = _INTERVALLE_MIN_S,
    ):
        self._base_url = (base_url if base_url is not None else settings.nt360_base_url).rstrip("/")
        api_key = api_key if api_key is not None else settings.nt360_api_key
        if not api_key:
            raise ValueError("nt360 : clé API absente (NT360_API_KEY)")
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self._sleep = sleep
        self._max_retries = max_retries
        self._intervalle_min_s = intervalle_min_s
        self._verrou_debit = asyncio.Lock()
        self._prochain_depart = 0.0

    async def close(self):
        await self._client.aclose()

    # ── Transport ───────────────────────────────────────────────────────────

    @staticmethod
    def _decode(resp: httpx.Response) -> Any:
        text = resp.content.decode("utf-8", errors="replace")
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {"error": text[:300]}

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        raw = resp.headers.get("retry-after")
        try:
            return max(0.0, float(raw)) if raw is not None else None
        except ValueError:
            return None   # forme date HTTP : non gérée, on retombe sur le backoff

    def _backoff(self, attempt: int) -> float:
        return min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * 2 ** attempt)

    async def _attendre_son_tour(self) -> None:
        """Espace les départs de requêtes d'au moins `intervalle_min_s`, toutes
        coroutines confondues : le quota est par clé, pas par appelant."""
        if self._intervalle_min_s <= 0:
            return
        async with self._verrou_debit:
            maintenant = time.monotonic()
            attente = self._prochain_depart - maintenant
            self._prochain_depart = max(maintenant, self._prochain_depart) + self._intervalle_min_s
        if attente > 0:
            await asyncio.sleep(attente)

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        """GET avec nouvelles tentatives sur 429, 5xx et erreurs réseau.

        Retourne None sur 404 (élément introuvable) ; lève Nt360AuthError sur
        401/403 sans retenter — une clé révoquée ne le sera pas moins dans 2 s.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        for attempt in range(self._max_retries + 1):
            dernier = attempt == self._max_retries
            await self._attendre_son_tour()
            try:
                resp = await self._client.get(url, params=params)
            except httpx.TransportError as e:
                if dernier:
                    raise Nt360Error(f"nt360 injoignable ({path}) : {e}") from e
                delay = self._backoff(attempt)
                logger.warning("nt360 %s : erreur réseau (%s), nouvel essai dans %.0f s", path, e, delay)
                await self._sleep(delay)
                continue

            code = resp.status_code
            if code == 200:
                return self._decode(resp)
            message = (self._decode(resp) or {}).get("error") or resp.reason_phrase
            if code in (401, 403):
                raise Nt360AuthError(f"nt360 {code} ({path}) : {message}", code)
            if code == 404:
                return None
            if code == 429 or code >= 500:
                if dernier:
                    raise Nt360Error(f"nt360 {code} ({path}) après {attempt + 1} essais : {message}", code)
                delay = self._retry_after(resp) if code == 429 else None
                delay = self._backoff(attempt) if delay is None else delay
                logger.warning("nt360 %s : %d, nouvel essai dans %.0f s", path, code, delay)
                await self._sleep(delay)
                continue
            raise Nt360Error(f"nt360 {code} ({path}) : {message}", code)
        raise AssertionError("inatteignable")

    # ── Lecture ─────────────────────────────────────────────────────────────

    async def iter_pages(self, resource: str, *, limit: int = PAGE_MAX, **filtres) -> AsyncIterator[dict]:
        """Itère les réponses brutes page par page en suivant `suite` → `apres`."""
        params = {"limit": min(limit, PAGE_MAX), **{k: v for k, v in filtres.items() if v is not None}}
        vus: set[str] = set()
        for _ in range(_MAX_PAGES):
            body = await self._get(resource, params)
            if body is None:
                raise Nt360Error(f"nt360 : ressource inconnue ({resource})", 404)
            yield body
            suite = body.get("suite")
            if not suite or suite in vus:
                return
            vus.add(suite)
            params = {**params, "apres": suite}
        logger.error("nt360 %s : garde-fou de %d pages atteint", resource, _MAX_PAGES)

    async def fetch_all(self, resource: str, *, limit: int = PAGE_MAX, **filtres) -> Nt360Liste:
        """Lit toute une ressource. Voir Nt360Liste.complete pour la troncature."""
        out = Nt360Liste()
        page_limit = min(limit, PAGE_MAX)
        dernier: dict = {}
        async for body in self.iter_pages(resource, limit=page_limit, **filtres):
            out.pages += 1
            out.items.extend(body.get("data") or [])
            dernier = body
        if dernier.get("suite"):
            out.complete = False   # sortie par le garde-fou de pages
        elif out.pages == 1 and len(out.items) >= page_limit:
            out.complete = False
            logger.warning(
                "nt360 %s %s : %d éléments pour limit=%d sans suite — liste probablement tronquée",
                resource, filtres or "", len(out.items), page_limit,
            )
        return out

    async def get(self, resource: str, item_id: str) -> dict | None:
        """Un élément par identifiant ; None s'il est introuvable.

        L'identifiant est encodé entièrement : un N° FP contient des « / »
        (FP/2026/142 → FP%2F2026%2F142), un nom de fournisseur des espaces.
        """
        body = await self._get(f"{resource}/{quote(str(item_id), safe='')}")
        return body.get("data") if body else None

    async def get_synthese(self, nom: str, entite: str | None = None) -> dict | None:
        params = {"entite": entite} if entite else None
        body = await self._get(f"syntheses/{quote(nom, safe='')}", params)
        return body.get("data") if body else None
