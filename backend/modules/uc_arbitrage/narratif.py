"""Avocat du contraire — la seule partie du dossier d'arbitrage confiée au
LLM. Les positions, l'enjeu et les deux options (aggregation.py) sont
entièrement déterministes ; ici, on demande à Claude d'argumenter CONTRE
l'option recommandée, à partir des mêmes chiffres réels, jamais de nouveaux
chiffres. Repli déterministe si l'appel échoue — même garde-fou que
uc_forecast/decision_client.py.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_SYSTEM = (
    "Tu es « avocat du contraire » dans un comité de direction d'ESN ivoirienne. "
    "On te donne une décision recommandée et les chiffres réels qui la motivent. "
    "Ton rôle est d'argumenter CONTRE cette recommandation, en français, de façon "
    "concise et factuelle — jamais d'inventer de chiffre absent du contexte fourni."
)

_USER_TEMPLATE = """Dossier : {subject_label}
Enjeu : {enjeu_m} M FCFA
Option recommandée : {option_titre} — {option_description}

Réponds STRICTEMENT en JSON, sans texte autour :
{{"raisons": ["raison 1 en une phrase", "raison 2 en une phrase"]}}"""


def _clean_json(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        nl = raw.find("\n")
        raw = raw[nl + 1:] if nl != -1 else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return _TRAILING_COMMA_RE.sub(r"\1", raw).strip()


def _fallback_raisons(dossier: dict, option: dict) -> list[str]:
    enjeu_m = round(dossier["enjeu_xof"] / 1_000_000)
    return [
        f"Bloquer l'engagement commercial fait courir un risque réel de perdre les {enjeu_m} M FCFA au profit d'un concurrent pendant la négociation du recouvrement.",
        "Le motif réel du retard de paiement n'est pas connu du miroir — un client par ailleurs solvable ne doit pas être traité comme un mauvais payeur sans vérification.",
    ]


async def build_counter_argument(llm, dossier: dict, option: dict) -> list[str]:
    fallback = _fallback_raisons(dossier, option)
    if llm is None:
        return fallback
    try:
        user = _USER_TEMPLATE.format(
            subject_label=dossier["subject_label"],
            enjeu_m=round(dossier["enjeu_xof"] / 1_000_000),
            option_titre=option["titre"],
            option_description=option["description"],
        )
        raw = await llm.generate(system=_SYSTEM, user=user, max_tokens=450, temperature=0.3)
        data = json.loads(_clean_json(raw))
        raisons = [str(r).strip() for r in data.get("raisons", []) if str(r).strip()]
        return raisons if len(raisons) >= 1 else fallback
    except Exception as exc:
        logger.warning("Avocat du contraire IA échoué (repli déterministe) : %s", exc)
        return fallback
