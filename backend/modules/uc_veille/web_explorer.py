"""Exploration web de l'agent Watch-Tracker (option « Explorer Internet »).

Utilise l'outil serveur web_search de Claude (aucune clé tierce) pour trouver des
opportunités liées aux thèmes prioritaires configurés, en plus des sources internes
scannées par modules/uc_veille/scanner.py. Renvoie des entrées au même format que
le scanner (title/url/description/…), avec origin="web".
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_SYSTEM = (
    "Tu es l'analyste veille d'une ESN ivoirienne (S2I) spécialisée en infrastructures, "
    "réseaux et cybersécurité à Abidjan. Tu recherches sur le web des opportunités "
    "commerciales réelles et récentes (appels d'offres, nominations, incidents, "
    "recrutements IT) liées aux thèmes fournis, en Côte d'Ivoire en priorité. Tu "
    "réponds UNIQUEMENT par un tableau JSON valide, sans texte autour."
)

_USER_TEMPLATE = """Thèmes prioritaires : {themes}

Cherche sur le web jusqu'à {max_results} opportunités récentes et concrètes liées à ces
thèmes (Côte d'Ivoire en priorité). Pour chacune, renvoie un objet avec EXACTEMENT ces
champs, sous forme de tableau JSON :
[
  {{
    "title": "titre court et factuel",
    "url": "lien DIRECT vers l'annonce elle-même (voir règle URL ci-dessous)",
    "description": "1-2 phrases résumant le signal",
    "organisation": "organisation concernée si identifiable, sinon vide"
  }}
]

Règle URL (importante) : l'URL doit pointer vers l'annonce précise elle-même, jamais
vers une page qui liste plusieurs offres (ex. pas ".../appels-offres" tout court).
Si un résultat de recherche ne te donne que ce type de page de liste générale, utilise
l'outil de récupération de page pour l'ouvrir et en extraire le lien direct de l'offre
concernée. Si tu ne trouves vraiment aucun lien direct, laisse "url" vide plutôt que de
mettre le lien générique.

N'invente rien : chaque entrée doit provenir d'un résultat de recherche réel. Si tu ne
trouves rien de pertinent, renvoie []."""


def _try_parse(candidate: str) -> str | None:
    """Corrige les virgules trailing puis vérifie que le candidat parse en JSON ET
    correspond à la forme attendue (liste d'objets, éventuellement vide).

    Un simple `json.loads()` réussi ne suffit PAS : un crochet isolé du préambule
    (ex. une citation « [1] ») est *aussi* du JSON valide (liste d'entiers) mais
    de la mauvaise forme — sans ce filtre de forme, on retiendrait ce faux positif
    au lieu de continuer à chercher le vrai tableau d'objets plus loin."""
    fixed = _TRAILING_COMMA_RE.sub(r"\1", candidate).strip()
    try:
        parsed = json.loads(fixed)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(x, dict) for x in parsed):
        return None
    return fixed


def _extract_balanced_array(raw: str, start_idx: int) -> str | None:
    """Depuis raw[start_idx] == '[', retrouve le ']' correspondant en comptant la
    profondeur des crochets et en ignorant ceux situés à l'intérieur d'une chaîne
    JSON. Renvoie le sous-texte complet, ou None si mal formé/non refermé."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start_idx, len(raw)):
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return raw[start_idx:i + 1]
    return None


def _clean_json_array(raw: str) -> str:
    """Extrait le tableau JSON de la réponse de Claude, même entouré de texte
    (Claude ajoute parfois un préambule avant le JSON malgré la consigne
    « réponds UNIQUEMENT par du JSON »). Teste plusieurs candidats et ne retient
    que celui qui parse réellement — jamais seulement le 1er '[' / dernier ']' du
    texte brut, qui peut être trompé par un crochet isolé dans le préambule
    (ex. une citation « [1] »)."""
    raw = (raw or "").strip()

    # 1) Blocs de code ```...``` contenant un tableau JSON, où qu'ils soient dans
    # la réponse (gère le cas fréquent d'une phrase d'intro avant la fence).
    for match in re.finditer(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL):
        parsed = _try_parse(match.group(1))
        if parsed is not None:
            return parsed

    # 2) Chaque '[' du texte comme candidat de début de tableau, crochet fermant
    # retrouvé par comptage de profondeur — insensible aux crochets isolés du
    # préambule puisqu'on ne retient que le premier candidat qui parse vraiment.
    idx = raw.find("[")
    while idx != -1:
        candidate = _extract_balanced_array(raw, idx)
        if candidate is not None:
            parsed = _try_parse(candidate)
            if parsed is not None:
                return parsed
        idx = raw.find("[", idx + 1)

    # 3) Repli historique (comportement d'avant le durcissement, jamais pire).
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        return _TRAILING_COMMA_RE.sub(r"\1", raw[start:end + 1]).strip()
    return raw


async def explore_web(llm, themes: str, max_results: int = 5) -> list[dict]:
    """Renvoie une liste d'entrées brutes (même forme que scan_rss_feed/scan_html_page)."""
    themes = (themes or "").strip()
    if not themes or llm is None or not hasattr(llm, "generate_with_web_search"):
        return []
    raw = ""
    try:
        user = _USER_TEMPLATE.format(themes=themes[:500], max_results=max_results)
        raw = await llm.generate_with_web_search(
            system=_SYSTEM, user=user, max_tokens=1500, max_uses=max_results,
        )
        items = json.loads(_clean_json_array(raw))
        if not isinstance(items, list):
            logger.warning(
                "Exploration web : réponse IA non exploitable (pas une liste JSON), ignorée. "
                "Réponse brute (tronquée) : %s", raw[:1000],
            )
            return []
    except Exception as exc:
        logger.warning(
            "Exploration web échouée (ignorée) : %s | Réponse brute (tronquée) : %s",
            exc, raw[:1000] if raw else "(aucune réponse reçue)",
        )
        return []

    entries = []
    for it in items[:max_results]:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        entries.append({
            "title": str(it.get("title", ""))[:500],
            "url": str(it.get("url", ""))[:500],
            "description": str(it.get("description", ""))[:2000],
            "published_at": None,
            "estimated_budget": "",
            "deadline": "",
            "relevance_score": 60,  # score neutre ; la criticité réelle vient du classifier
            "origin": "web",
            "organisation": str(it.get("organisation", ""))[:255],
        })
    return entries
