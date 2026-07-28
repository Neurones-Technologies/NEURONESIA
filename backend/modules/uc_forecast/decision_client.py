"""Décision recommandée par client sur le forecast.

Le niveau de risque (conditionner / requalifier / sécuriser) est calculé en
Python à partir de faits réels (impayé connu via get_unpaid_exposure(),
opportunité à échéance dépassée) — jamais laissé au LLM, qui ne fait que
rédiger la justification et l'action. Même garde-fou anti-hallucination que
la recommandation GO/NO_BID du scoring d'appels d'offres (uc10_presales).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_DECISION_LABELS = {
    "conditionner_requalifier": "Conditionner et requalifier",
    "conditionner": "Conditionner",
    "requalifier": "Requalifier",
    "securiser": "Sécuriser",
}

_SYSTEM = (
    "Tu es directeur commercial d'une ESN ivoirienne (S2I). On te donne une "
    "décision de gestion de compte déjà déterminée par les règles de risque de "
    "l'entreprise : tu rédiges uniquement sa justification et une première "
    "action concrète, en français. Tu ne dois JAMAIS changer la décision fournie."
)

_USER_TEMPLATE = """Client : {client}
Décision imposée (ne pas modifier) : {decision_label}
Valeur pondérée du forecast pour ce client : {pondere_m_fcfa} M FCFA
Impayé connu : {impaye_texte}
Opportunité à échéance dépassée : {opp_risque_texte}

Réponds STRICTEMENT en JSON, sans texte autour :
{{"justification": "une phrase basée uniquement sur les faits ci-dessus", "action": "une action concrète à mener sous 7 jours"}}"""


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


def _classify_risk(debiteur: dict | None, opp_risque: dict | None) -> str:
    """Règle déterministe — identique à l'ancienne logique JS decisionClient()."""
    if debiteur and opp_risque:
        return "conditionner_requalifier"
    if debiteur:
        return "conditionner"
    if opp_risque:
        return "requalifier"
    return "securiser"


def _fallback_texts(decision_key: str, *, pondere_m_fcfa: int,
                     debiteur: dict | None, opp_risque: dict | None) -> dict:
    """Repli déterministe (mêmes règles que l'ancien decisionClient() front)."""
    if decision_key == "conditionner_requalifier":
        return {
            "justification": (
                f"Ce client cumule {debiteur['montant_total_xof'] / 1_000_000:.0f} M FCFA d'impayés "
                f"et une opportunité à échéance dépassée ({opp_risque['name']}) — conditionner tout "
                "nouvel engagement au recouvrement, et requalifier l'opportunité."
            ),
            "action": "Organiser cette semaine un point recouvrement + revue d'opportunité avec le commercial en charge.",
        }
    if decision_key == "conditionner":
        return {
            "justification": (
                f"{pondere_m_fcfa} M FCFA de forecast pondéré, mais "
                f"{debiteur['montant_total_xof'] / 1_000_000:.0f} M FCFA d'impayés "
                f"({debiteur['retard_max_jours']} jours de retard) — sécuriser le recouvrement avant "
                "d'investir davantage commercialement."
            ),
            "action": "Lancer la relance de recouvrement avant toute nouvelle proposition.",
        }
    if decision_key == "requalifier":
        return {
            "justification": (
                f"{opp_risque['name']} a dépassé son échéance prévue — sa probabilité déclarée gonfle "
                "artificiellement le forecast de ce client."
            ),
            "action": "Contacter le client cette semaine pour confirmer si le besoin existe encore ; sinon, clôturer l'opportunité.",
        }
    return {
        "justification": f"{pondere_m_fcfa} M FCFA pondérés sans signal de risque ni impayé connu — un forecast à défendre activement.",
        "action": "Fixer la prochaine étape avec le client (rendez-vous ou envoi de proposition) sous 7 jours.",
    }


async def build_client_decision(llm, *, client: str, pondere_xof: float,
                                 debiteur: dict | None, opp_risque: dict | None) -> dict:
    decision_key = _classify_risk(debiteur, opp_risque)
    decision_label = _DECISION_LABELS[decision_key]
    pondere_m_fcfa = round(pondere_xof / 1_000_000)
    fallback = _fallback_texts(
        decision_key, pondere_m_fcfa=pondere_m_fcfa, debiteur=debiteur, opp_risque=opp_risque,
    )

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
            client=client,
            decision_label=decision_label,
            pondere_m_fcfa=pondere_m_fcfa,
            impaye_texte=(
                f"{debiteur['montant_total_xof'] / 1_000_000:.0f} M FCFA "
                f"({debiteur['retard_max_jours']} jours de retard)"
                if debiteur else "aucun"
            ),
            opp_risque_texte=(f"{opp_risque['name']} (échéance dépassée)" if opp_risque else "aucune"),
        )
        raw = await llm.generate(system=_SYSTEM, user=user, max_tokens=300, temperature=0)
        data = json.loads(_clean_json(raw))
        justification = str(data.get("justification") or "").strip()
        action = str(data.get("action") or "").strip()
        if justification and action:
            result["justification"] = justification
            result["action"] = action
            result["ai_generated"] = True
    except Exception as exc:
        logger.warning("Décision IA forecast échouée (repli règles) : %s", exc)
    return result
