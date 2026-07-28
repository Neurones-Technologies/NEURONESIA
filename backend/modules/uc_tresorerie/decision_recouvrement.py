"""Décision de recouvrement par impayé.

Le niveau d'urgence (recouvrement d'urgence / plan structuré / relance active)
est calculé en Python à partir du retard réel (jours de retard, table
invoices) — jamais laissé au LLM. Claude ne rédige que la justification et la
première action. Même garde-fou anti-hallucination que decision_client.py
(module uc_forecast) et le scoring d'appels d'offres (uc10_presales).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_DECISION_LABELS = {
    "urgence": "Recouvrement d'urgence",
    "structure": "Plan de recouvrement structuré",
    "relance": "Relance active",
}

_SYSTEM = (
    "Tu es directeur financier d'une ESN ivoirienne (S2I). On te donne un "
    "niveau d'urgence de recouvrement déjà déterminé par les règles de "
    "l'entreprise (basées sur le retard réel) : tu rédiges uniquement sa "
    "justification et une première action, en français. Tu ne dois JAMAIS "
    "changer le niveau fourni."
)

_USER_TEMPLATE = """Client : {client}
Montant échu : {montant_m_fcfa} M FCFA
Retard : {jours} jours
Niveau imposé (ne pas modifier) : {decision_label}

Réponds STRICTEMENT en JSON, sans texte autour :
{{"justification": "une phrase basée uniquement sur les faits ci-dessus", "action": "une action concrète à mener"}}"""


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


def _classify_urgence(jours: int) -> str:
    """Règle déterministe — identique à l'ancienne logique JS decisionRecouvrement()."""
    if jours > 700:
        return "urgence"
    if jours > 400:
        return "structure"
    return "relance"


def _fallback_texts(decision_key: str, *, montant_m_fcfa: int, jours: int) -> dict:
    """Repli déterministe (mêmes règles que l'ancien decisionRecouvrement() front)."""
    if decision_key == "urgence":
        return {
            "justification": (
                f"{jours} jours de retard — c'est un impayé proche du seuil où une créance devient "
                "comptablement irrécouvrable."
            ),
            "action": "Escalade immédiate (Direction Financière + Direction Commerciale) sous 5 jours, avant provision pour créance douteuse.",
        }
    if decision_key == "structure":
        return {
            "justification": (
                f"Montant significatif ({montant_m_fcfa} M FCFA) en souffrance depuis plus d'un an "
                f"({jours} jours) — nécessite un suivi dédié, pas une simple relance."
            ),
            "action": "Mettre en place une cellule de recouvrement dédiée avec échéancier formel sous 15 jours.",
        }
    return {
        "justification": f"{jours} jours de retard — encore dans une fenêtre où une relance ferme peut suffire.",
        "action": "Relance formelle sous 7 jours, avant que le dossier ne s'aggrave.",
    }


async def build_recouvrement_decision(llm, *, client: str, montant_xof: float, jours: int) -> dict:
    decision_key = _classify_urgence(jours)
    decision_label = _DECISION_LABELS[decision_key]
    montant_m_fcfa = round(montant_xof / 1_000_000)
    fallback = _fallback_texts(decision_key, montant_m_fcfa=montant_m_fcfa, jours=jours)

    result = {
        "decision_key": decision_key,
        "decision_label": decision_label,
        "justification": fallback["justification"],
        "action": fallback["action"],
        "ai_generated": False,
    }
    if llm is None:
        return result
    try:
        user = _USER_TEMPLATE.format(
            client=client, montant_m_fcfa=montant_m_fcfa, jours=jours, decision_label=decision_label,
        )
        raw = await llm.generate(system=_SYSTEM, user=user, max_tokens=250, temperature=0)
        data = json.loads(_clean_json(raw))
        justification = str(data.get("justification") or "").strip()
        action = str(data.get("action") or "").strip()
        if justification and action:
            result["justification"] = justification
            result["action"] = action
            result["ai_generated"] = True
    except Exception as exc:
        logger.warning("Décision IA recouvrement échouée (repli règles) : %s", exc)
    return result
