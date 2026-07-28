"""Analyse transversale « montée en valeur », rédigée par Claude à partir des
signaux déjà calculés (aggregation.py) — jamais recalculés par le LLM.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur commercial d'une ESN ivoirienne (S2I). Tu commentes des signaux de montée en valeur "
    "(cross-sell, up-sell, renouvellement, obsolescence) déjà détectés sur les vraies commandes clients. "
    "Ton travail n'est pas de reformuler les chiffres qu'on te donne, mais de dire ce qu'ils changent "
    "pour la semaine commerciale : où est l'argent qui risque d'être perdu si personne n'agit, et où est "
    "l'argent facile à sécuriser.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. Le signal prioritaire et le raisonnement complet derrière — pas juste le montant, mais pourquoi "
    "CE signal-là passe avant les autres (urgence, taille, ou risque de le perdre à un concurrent).\n"
    "2. Ce que les autres catégories de signaux (renouvellement, obsolescence, cross-sell, up-sell) "
    "révèlent une fois comparées entre elles — une catégorie domine-t-elle anormalement, ou sont-elles "
    "équilibrées ?\n"
    "3. Une action concrète, avec le nom du client et le montant en jeu, à mener cette semaine."
)

_USER_TEMPLATE = """Signaux détectés sur les commandes réelles :
- Renouvellements à traiter : {nb_renouvellement}
- Catégories obsolètes (>24 mois sans achat) : {nb_obsolete}
- Opportunités de cross-sell (catégorie achetée sans son complément) : {nb_cross_sell}
- Opportunités d'up-sell (client mono-catégorie, dépense significative) : {nb_up_sell}
- Signal le plus important : {top_signal_type} chez {top_signal_client} — {top_signal_montant} M FCFA ({top_signal_detail})

Rédige l'analyse en 3 paragraphes courts, aucune invention de montant ou de nom au-delà de ceux fournis."""


def _fallback_analysis(ctx: dict) -> str:
    return "\n\n".join([
        f"Signal prioritaire : {ctx['top_signal_type']} chez {ctx['top_signal_client']} "
        f"({ctx['top_signal_montant']} M FCFA, {ctx['top_signal_detail']}) — c'est l'enjeu le plus élevé "
        "détecté cette semaine, à traiter avant les autres.",
        f"{ctx['nb_renouvellement']} renouvellement(s), {ctx['nb_obsolete']} catégorie(s) obsolète(s), "
        f"{ctx['nb_cross_sell']} opportunité(s) de cross-sell et {ctx['nb_up_sell']} d'up-sell sont "
        "détectés au total sur les commandes réelles du portefeuille — à répartir entre les commerciaux "
        "selon la taille de l'enjeu plutôt que dans l'ordre où ils apparaissent.",
        f"Action immédiate : contacter {ctx['top_signal_client']} au sujet de {ctx['top_signal_type'].lower()} "
        f"avant que les {ctx['top_signal_montant']} M FCFA identifiés ne soient remis en question.",
    ])


async def build_crosssell_analysis(llm, ctx: dict) -> str:
    if llm is None:
        return _fallback_analysis(ctx)
    try:
        user = _USER_TEMPLATE.format(**ctx)
        text = await llm.generate(system=_SYSTEM, user=user, max_tokens=750, temperature=0.5)
        return (text or "").strip() or _fallback_analysis(ctx)
    except Exception as exc:
        logger.warning("Analyse IA montée en valeur échouée (repli calculs réels) : %s", exc)
        return _fallback_analysis(ctx)
