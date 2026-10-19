"""Client nt360 : pagination, troncature muette, nouvelles tentatives, encodage.

Aucun appel réseau : httpx.MockTransport joue le serveur, et `sleep` est
remplacé par un enregistreur pour vérifier les attentes sans les subir.
"""
import httpx
import pytest

from adapters.nt360.nt360_adapter import Nt360Adapter, Nt360AuthError, Nt360Error

BASE = "https://nt360.test/api/v1"


def _adapter(handler, **kw):
    attentes: list[float] = []

    async def sleep(s):
        attentes.append(s)

    kw.setdefault("intervalle_min_s", 0)     # pas de limiteur de débit hors test dédié
    a = Nt360Adapter(BASE, "nt360_test", transport=httpx.MockTransport(handler), sleep=sleep, **kw)
    return a, attentes


def _json(code, body, headers=None):
    return httpx.Response(code, json=body, headers=headers)


# ── Pagination ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suit_le_curseur_jusqua_suite_null_meme_avec_pages_courtes():
    pages = {
        None: {"data": [{"id": 1}, {"id": 2}], "count": 2, "suite": "c1"},
        "c1": {"data": [{"id": 3}], "count": 1, "suite": "c2"},   # page courte, pas la dernière
        "c2": {"data": [{"id": 4}], "count": 1, "suite": None},
    }
    vus = []

    def handler(req):
        vus.append(dict(req.url.params))
        assert req.headers["authorization"] == "Bearer nt360_test"
        return _json(200, pages[req.url.params.get("apres")])

    a, _ = _adapter(handler)
    res = await a.fetch_all("factures", limit=2)

    assert [x["id"] for x in res.items] == [1, 2, 3, 4]
    assert res.pages == 3 and res.complete
    assert vus[0] == {"limit": "2"} and vus[2] == {"limit": "2", "apres": "c2"}


@pytest.mark.asyncio
async def test_limit_plafonne_a_500():
    def handler(req):
        assert req.url.params["limit"] == "500"
        return _json(200, {"data": [], "count": 0, "suite": None})

    a, _ = _adapter(handler)
    await a.fetch_all("bc", limit=10_000)


@pytest.mark.asyncio
async def test_curseur_repete_ne_boucle_pas():
    def handler(req):
        return _json(200, {"data": [{"id": 1}], "count": 1, "suite": "toujours-le-meme"})

    a, _ = _adapter(handler)
    res = await a.fetch_all("commandes")
    assert res.pages == 2


@pytest.mark.asyncio
async def test_filtres_none_ne_sont_pas_envoyes():
    def handler(req):
        assert dict(req.url.params) == {"limit": "500", "stage": "6"}
        return _json(200, {"data": [], "count": 0, "suite": None})

    a, _ = _adapter(handler)
    await a.fetch_all("opportunities", stage=6, bu=None)


# ── Troncature muette (opportunities / accounts sans `suite`) ───────────────

@pytest.mark.asyncio
async def test_liste_pleine_sans_suite_est_marquee_incomplete():
    def handler(req):
        n = int(req.url.params["limit"])
        return _json(200, {"data": [{"id": i} for i in range(n)], "count": n, "suite": None})

    a, _ = _adapter(handler)
    res = await a.fetch_all("opportunities", limit=500, stage=6)
    assert len(res.items) == 500 and not res.complete


@pytest.mark.asyncio
async def test_liste_courte_sans_suite_est_complete():
    def handler(req):
        return _json(200, {"data": [{"id": 1}], "count": 1, "suite": None})

    a, _ = _adapter(handler)
    assert (await a.fetch_all("objectifs")).complete


# ── Erreurs et nouvelles tentatives ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_429_respecte_retry_after_puis_reussit():
    reponses = iter([
        _json(429, {"error": "quota"}, {"Retry-After": "7"}),
        _json(200, {"data": [], "count": 0, "suite": None}),
    ])
    a, attentes = _adapter(lambda req: next(reponses))
    await a.fetch_all("factures")
    assert attentes == [7.0]


@pytest.mark.asyncio
async def test_500_retente_avec_backoff_exponentiel_puis_abandonne():
    appels = []

    def handler(req):
        appels.append(1)
        return _json(500, {"error": "interne"})

    a, attentes = _adapter(handler, max_retries=3)
    with pytest.raises(Nt360Error) as e:
        await a.fetch_all("factures")
    assert e.value.status_code == 500
    assert len(appels) == 4 and attentes == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_erreur_reseau_est_retentee():
    reponses = iter([httpx.ConnectError("boom"), _json(200, {"data": {"fp": "FP/2026/1"}})])

    def handler(req):
        r = next(reponses)
        if isinstance(r, Exception):
            raise r
        return r

    a, attentes = _adapter(handler)
    assert await a.get("commandes", "FP/2026/1") == {"fp": "FP/2026/1"}
    assert attentes == [1.0]


@pytest.mark.parametrize("code", [401, 403])
@pytest.mark.asyncio
async def test_401_403_ne_sont_jamais_retentes(code):
    appels = []

    def handler(req):
        appels.append(1)
        return _json(code, {"error": "clé révoquée"})

    a, attentes = _adapter(handler)
    with pytest.raises(Nt360AuthError) as e:
        await a.fetch_all("factures")
    assert e.value.status_code == code and len(appels) == 1 and attentes == []


@pytest.mark.asyncio
async def test_message_derreur_decode_en_utf8_sans_charset():
    # Corps UTF-8 servi sans charset, comme le fait nt360 (« cl� API invalide »).
    corps = '{"error":"clé API invalide ou révoquée"}'.encode("utf-8")

    def handler(req):
        return httpx.Response(401, content=corps, headers={"content-type": "application/json"})

    a, _ = _adapter(handler)
    with pytest.raises(Nt360AuthError, match="clé API invalide ou révoquée"):
        await a.fetch_all("factures")


# ── Lecture unitaire et synthèses ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_encode_le_numero_fp_et_renvoie_none_sur_404():
    chemins = []

    def handler(req):
        chemins.append(req.url.raw_path.decode())
        return _json(404, {"error": "introuvable"})

    a, _ = _adapter(handler)
    assert await a.get("commandes", "FP/2026/142") is None
    assert chemins == ["/api/v1/commandes/FP%2F2026%2F142"]


@pytest.mark.asyncio
async def test_get_synthese_passe_lentite():
    def handler(req):
        assert req.url.path == "/api/v1/syntheses/overview_2026"
        assert req.url.params["entite"] == "CI"
        return _json(200, {"data": {"commandes": 1}})

    a, _ = _adapter(handler)
    assert await a.get_synthese("overview_2026", entite="CI") == {"commandes": 1}


def test_cle_absente_refusee():
    with pytest.raises(ValueError):
        Nt360Adapter(BASE, "")


@pytest.mark.asyncio
async def test_limiteur_espace_les_requetes_meme_en_parallele():
    """Le quota (600/min) est par clé : des lectures parallèles doivent partir
    espacées, sans quoi la relecture unitaire déclenche des 429 en rafale."""
    import asyncio
    import time
    departs = []

    def handler(req):
        departs.append(time.monotonic())
        return _json(200, {"data": {}})

    a, _ = _adapter(handler, intervalle_min_s=0.05)
    await asyncio.gather(*(a.get("opportunities", f"o{i}") for i in range(5)))
    etendue = max(departs) - min(departs)
    assert len(departs) == 5 and etendue >= 4 * 0.05 * 0.8   # 4 intervalles, tolérance horloge
