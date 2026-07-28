"""Agent d'analyse Watch-Tracker : un signal de veille brut → opportunité S2I.

`classify_entry` interroge Claude (via LLMGateway) pour rattacher le signal à la
grille S2I (signal → risque → offre), lui donner une priorité + un score de
criticité argumenté, et extraire l'organisation concernée. En cas d'échec Claude
(indisponible, JSON invalide), repli déterministe par mots-clés — jamais bloquant.

Le texte canonique du risque/de l'offre provient toujours de la grille locale
quand le signal est reconnu : Claude choisit la catégorie, pas la formulation.
"""
from __future__ import annotations

import json
import logging
import re

from modules.uc_veille.s2i_grille import (
    FALLBACK_RULE,
    PRIORITY_ORDER,
    S2IRule,
    classify_by_keywords,
    grille_for_prompt,
    rule_by_id,
)

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_SYSTEM = (
    "Tu es l'analyste avant-vente d'une ESN ivoirienne (S2I) spécialisée en "
    "infrastructures, réseaux et cybersécurité à Abidjan. À partir d'un signal de "
    "veille brut, tu détermines s'il s'agit d'une opportunité commerciale actionnable "
    "et tu le rattaches à la grille S2I fournie. Tu réponds UNIQUEMENT par un objet "
    "JSON valide, sans texte autour."
)

_USER_TEMPLATE = """Grille S2I (signal → risque → offre) :
{grille}

Thèmes prioritaires de l'entreprise (à privilégier dans l'évaluation de la pertinence et de la criticité) : {themes}

Signal de veille détecté :
Titre : {title}
Description : {description}

Analyse ce signal et renvoie STRICTEMENT ce JSON :
{{
  "pertinent": true,               // false si c'est du bruit non actionnable pour une ESN
  "signal_id": "<id de la grille ci-dessus, ou \\"a-qualifier\\" si aucun ne correspond>",
  "priority": "CRITIQUE|ELEVEE|MOYENNE",
  "criticite": 0,                  // entier 0-100, urgence/valeur commerciale du signal
  "organisation": "",              // organisation/entité concernée si identifiable, sinon ""
  "risque": "",                    // À REMPLIR UNIQUEMENT si signal_id = "a-qualifier"
  "offre": "",                     // idem : offre S2I proposée si "a-qualifier"
  "offre_short": "",               // idem : étiquette courte de l'offre
  "justification": ""              // une phrase expliquant le rattachement et la priorité
}}
Règles : si tu rattaches à un id existant de la grille, laisse risque/offre/offre_short vides
(je reprends le texte de la grille). Ne renvoie que le JSON."""


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


def _clamp(n, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(n)))
    except (TypeError, ValueError):
        return lo


def _result_from_rule(rule: S2IRule, *, ai_analyzed: bool, criticite: int = 0,
                      organisation: str = "", justification: str = "") -> dict:
    """Construit le dict de colonnes DB à partir d'une règle de la grille."""
    # Criticité par défaut dérivée de la priorité si l'IA n'en fournit pas.
    if criticite <= 0:
        criticite = {"CRITIQUE": 85, "ELEVEE": 60, "MOYENNE": 35}.get(rule.priority, 35)
    return {
        "ai_analyzed": ai_analyzed,
        "signal_label": rule.signal_label,
        "risque": rule.risque,
        "offre": rule.offre,
        "offre_short": rule.offre_short,
        "priority": rule.priority,
        "criticite": criticite,
        "organisation": (organisation or "")[:255],
        "justification": (justification or "")[:1000],
    }


def _fallback(title: str, description: str) -> dict:
    """Repli mots-clés : jamais d'exception, toujours un dict exploitable."""
    rule = classify_by_keywords(title, description)
    return _result_from_rule(rule, ai_analyzed=False)


async def classify_entry(llm, title: str, description: str, themes: str = "") -> dict:
    """Renvoie les colonnes S2I (dict prêt à fusionner dans l'entrée)."""
    if llm is None:
        return _fallback(title, description)
    try:
        user = _USER_TEMPLATE.format(
            grille=grille_for_prompt(),
            themes=(themes or "").strip() or "(aucun thème prioritaire défini)",
            title=(title or "")[:400],
            description=(description or "")[:1500],
        )
        raw = await llm.generate(system=_SYSTEM, user=user, max_tokens=400, temperature=0)
        data = json.loads(_clean_json(raw))
    except Exception as exc:  # LLM KO, JSON invalide, timeout… → repli
        logger.warning("Classification IA échouée (repli mots-clés) : %s", exc)
        return _fallback(title, description)

    criticite = _clamp(data.get("criticite", 0), 0, 100)
    organisation = str(data.get("organisation") or "")
    justification = str(data.get("justification") or "")
    signal_id = str(data.get("signal_id") or "").strip()

    rule = rule_by_id(signal_id)
    if rule is not None:
        # Signal reconnu → texte canonique de la grille, criticité IA conservée.
        return _result_from_rule(
            rule, ai_analyzed=True, criticite=criticite,
            organisation=organisation, justification=justification,
        )

    # « À qualifier » : on garde la proposition de Claude (risque/offre), sinon repli.
    priority = str(data.get("priority") or "").upper()
    if priority not in PRIORITY_ORDER:
        priority = FALLBACK_RULE.priority
    return {
        "ai_analyzed": True,
        "signal_label": FALLBACK_RULE.signal_label,
        "risque": (str(data.get("risque") or "") or FALLBACK_RULE.risque)[:500],
        "offre": (str(data.get("offre") or "") or FALLBACK_RULE.offre)[:500],
        "offre_short": (str(data.get("offre_short") or "") or FALLBACK_RULE.offre_short)[:100],
        "priority": priority,
        "criticite": criticite or 35,
        "organisation": organisation[:255],
        "justification": justification[:1000],
    }
