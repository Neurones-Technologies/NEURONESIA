"""Génération du pitch d'avant-vente Watch-Tracker par Claude.

Remplace le gabarit statique du front : à partir d'une entrée de veille et de son
analyse S2I (signal → risque → offre), Claude rédige un argumentaire prêt à
l'emploi. Repli honnête (sur les VRAIES données de l'entrée) si Claude échoue.
"""
from __future__ import annotations

import logging

from modules.uc_veille.s2i_grille import classify_by_keywords

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur avant-vente d'une ESN ivoirienne (S2I) spécialisée en "
    "infrastructures, réseaux et cybersécurité à Abidjan. Tu rédiges des pitchs "
    "d'avant-vente concis, concrets et orientés décideur, en français."
)

_USER_TEMPLATE = """Signal de veille détecté :
- Titre : {title}
- Description : {description}
- Organisation concernée : {organisation}
- Type de signal : {signal_label}
- Risque client : {risque}
- Offre S2I à positionner : {offre}
- Priorité : {priority}

Rédige un pitch d'avant-vente en Markdown, prêt à envoyer, avec EXACTEMENT ces sections :
**Contexte détecté** — 1 à 2 phrases sur le signal.
**Le risque pour le client** — l'exposition concrète.
**Notre réponse — {offre_short}** — comment l'offre S2I répond.
**Argumentaire d'ouverture** — 2 à 3 phrases percutantes à dire au client.
**Prochaine étape suggérée** — action commerciale adaptée à la priorité.
Reste factuel et spécifique au signal ; pas de remplissage générique."""


def _context(entry) -> dict:
    """Récupère le contexte S2I : analyse stockée en priorité, sinon repli mots-clés."""
    if getattr(entry, "signal_label", ""):
        return {
            "signal_label": entry.signal_label,
            "risque": entry.risque,
            "offre": entry.offre,
            "offre_short": entry.offre_short,
            "priority": entry.priority or "MOYENNE",
        }
    rule = classify_by_keywords(entry.title, entry.description or "")
    return {
        "signal_label": rule.signal_label,
        "risque": rule.risque,
        "offre": rule.offre,
        "offre_short": rule.offre_short,
        "priority": rule.priority,
    }


def _fallback_pitch(title: str, ctx: dict) -> str:
    """Repli sans Claude : construit à partir des VRAIES données (pas de fabrication)."""
    step = {
        "CRITIQUE": "Prise de contact sous 48 h — priorité critique.",
        "ELEVEE": "Prise de contact cette semaine — priorité élevée.",
    }.get(ctx["priority"], "Intégrer au plan de prospection du mois.")
    return "\n".join([
        "**Contexte détecté**",
        f"Signal : « {title} » ({ctx['signal_label']}).",
        "",
        "**Le risque pour le client**",
        ctx["risque"],
        "",
        f"**Notre réponse — {ctx['offre_short']}**",
        ctx["offre"],
        "",
        "**Prochaine étape suggérée**",
        step,
    ])


async def build_pitch(llm, entry) -> str:
    ctx = _context(entry)
    if llm is None:
        return _fallback_pitch(entry.title, ctx)
    try:
        user = _USER_TEMPLATE.format(
            title=(entry.title or "")[:400],
            description=(entry.description or "")[:1500],
            organisation=getattr(entry, "organisation", "") or "à identifier",
            **ctx,
        )
        text = await llm.generate(system=_SYSTEM, user=user, max_tokens=700, temperature=0.5)
        return (text or "").strip() or _fallback_pitch(entry.title, ctx)
    except Exception as exc:
        logger.warning("Génération pitch IA échouée (repli données réelles) : %s", exc)
        return _fallback_pitch(entry.title, ctx)
