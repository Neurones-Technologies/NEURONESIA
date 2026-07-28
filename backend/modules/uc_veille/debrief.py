"""Débriefing d'AO Watch-Tracker : Claude lit la page exacte de l'annonce (via
web_fetch, sur le lien direct de l'offre) et en extrait fidèlement ce qui est
demandé — avant même que le commercial ne quitte la plateforme pour aller lire
la source. Complète le pitch (qui vend l'offre S2I) par une lecture neutre du
besoin exprimé par le client, sans argumentaire commercial.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_OBJET_MARKER_RE = re.compile(r"\*\*Objet\*\*")

_SYSTEM = (
    "Tu es analyste avant-vente d'une ESN ivoirienne (S2I). Tu lis une page "
    "d'appel d'offres ou d'annonce et tu en extrais fidèlement ce qui est "
    "demandé, sans l'enjoliver ni y ajouter d'argumentaire commercial — cela "
    "sera fait séparément par un autre outil."
)

_USER_TEMPLATE = """Ouvre cette page et lis son contenu : {url}

Contexte issu de la veille (à titre indicatif uniquement, la page fait foi) :
- Titre : {title}
- Description : {description}

Rédige un débriefing en Markdown avec EXACTEMENT ces sections :
**Objet** — de quoi il s'agit concrètement, en 1-2 phrases.
**Ce qui est demandé** — le besoin/les livrables attendus, en liste à puces.
**Profil / éligibilité** — critères requis pour candidater, si mentionnés.
**Date limite** — si trouvée sur la page.
**Documents à fournir** — si mentionnés.

Si tu ne parviens pas à ouvrir la page, ou qu'elle ne contient pas ces
informations, dis-le clairement plutôt que d'inventer."""


def _fallback_debrief(entry) -> str:
    """Repli quand aucun lien exploitable n'est disponible, ou que la lecture a échoué."""
    return "\n".join([
        "**Objet**",
        entry.title,
        "",
        "**Ce qui est demandé**",
        "Aucun lien direct exploitable vers l'annonce n'est disponible pour cette "
        "opportunité — seule la description captée en veille est disponible :",
        "",
        entry.description or "(aucune description disponible)",
    ])


async def build_debrief(llm, entry) -> str:
    if not getattr(entry, "url", ""):
        return _fallback_debrief(entry)
    if llm is None or not hasattr(llm, "generate_with_url_fetch"):
        return _fallback_debrief(entry)
    try:
        user = _USER_TEMPLATE.format(
            url=entry.url,
            title=(entry.title or "")[:400],
            description=(entry.description or "")[:1000],
        )
        text = (await llm.generate_with_url_fetch(system=_SYSTEM, user=user, max_tokens=1200)).strip()
        # Claude ajoute parfois une phrase de transition avant le débriefing
        # structuré (ex. « Je vais ouvrir la page pour vous... ») malgré la
        # consigne de rester factuel — on retire tout ce qui précède **Objet**.
        match = _OBJET_MARKER_RE.search(text)
        if match:
            text = text[match.start():]
        return text or _fallback_debrief(entry)
    except Exception as exc:
        logger.warning("Débriefing AO échoué (repli) : %s", exc)
        return _fallback_debrief(entry)
