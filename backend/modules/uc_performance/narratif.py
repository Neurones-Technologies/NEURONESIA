"""Analyse qualitative des performances commerciales par Claude.

Les chiffres (taux de victoire, pertes) sont déjà calculés en Python à partir
des vraies opportunités (get_win_rate / get_lost_deals) — Claude ne fait que
les commenter, jamais les recalculer. Repli déterministe si Claude échoue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur commercial d'une ESN ivoirienne (S2I). Tu commentes des statistiques de performance "
    "commerciale déjà calculées, pour préparer une revue de portefeuille — le lecteur veut savoir sur "
    "quel compte agir, pas relire les pourcentages qu'il a déjà sous les yeux.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. Ce que l'écart entre taux de victoire en nombre et en valeur révèle vraiment (dossiers perdus "
    "structurellement plus gros ou plus petits que les dossiers gagnés) — et pourquoi ce déséquilibre "
    "est un problème de qualification, de prix, ou de concurrence si tu peux le déduire des chiffres.\n"
    "2. Le poids réel du client qui concentre le plus de pertes, comparé au reste du portefeuille — "
    "est-ce un cas isolé ou un signal structurel ?\n"
    "3. Une recommandation concrète : la question précise à poser en revue de compte sur ce client."
)

_USER_TEMPLATE = """Chiffres réels de performance commerciale (historique complet) :
- Taux de victoire en nombre d'opportunités : {taux_nb}%
- Taux de victoire en valeur : {taux_valeur}%
- Opportunités perdues : {nb_perdues}, pour {montant_perdu} M FCFA au total
- Client concentrant le plus de pertes : {top_client_name}, {top_client_montant} M FCFA sur {top_client_nb} opportunités

Rédige l'analyse en 3 paragraphes courts, aucune invention de montant ou de nom au-delà de ceux fournis."""


def _fallback_analysis(ctx: dict) -> str:
    """Repli déterministe : mêmes constats que l'ancien template JS, sur les vraies données."""
    ecart = ctx["taux_nb"] - ctx["taux_valeur"]
    tendance = "plus gros" if ecart > 0 else "plus petits"
    return "\n\n".join([
        f"Le taux de victoire en nombre ({ctx['taux_nb']}%) et en valeur ({ctx['taux_valeur']}%) "
        f"diffèrent nettement : les dossiers perdus sont structurellement {tendance} que les "
        "dossiers gagnés — un signal à vérifier sur le prix ou la qualification plutôt que sur le volume.",
        f"{ctx['top_client_name']} concentre le plus haut montant perdu "
        f"({ctx['top_client_montant']} M FCFA sur {ctx['top_client_nb']} opportunités) — largement "
        "devant tout autre client du portefeuille.",
        f"Recommandation : en revue de compte {ctx['top_client_name']}, demander explicitement si ces "
        f"{ctx['top_client_nb']} pertes partagent un même motif (prix, concurrent, délai) avant de "
        "conclure qu'il s'agit d'un hasard de calendrier.",
    ])


async def build_performance_analysis(llm, ctx: dict) -> str:
    """ctx : faits déjà calculés (jamais recalculés par le LLM)."""
    if llm is None:
        return _fallback_analysis(ctx)
    try:
        user = _USER_TEMPLATE.format(**ctx)
        text = await llm.generate(system=_SYSTEM, user=user, max_tokens=750, temperature=0.5)
        return (text or "").strip() or _fallback_analysis(ctx)
    except Exception as exc:
        logger.warning("Analyse IA performance échouée (repli calculs réels) : %s", exc)
        return _fallback_analysis(ctx)
