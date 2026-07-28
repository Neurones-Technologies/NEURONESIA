"""Analyse qualitative du forecast pondéré par Claude.

Les chiffres (concentration, écarts de scénarios) sont déjà calculés en Python
(aggregation.py) à partir des vraies opportunités du pipeline — Claude ne fait
que les commenter, jamais les recalculer. Repli déterministe si Claude échoue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur commercial d'une ESN ivoirienne (S2I). Tu commentes un forecast de pipeline "
    "commercial déjà calculé pour la Direction Commerciale, qui doit décider où concentrer l'attention "
    "cette semaine — pas seulement constater les chiffres, mais dire ce qu'ils obligent à faire.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. Le degré de concentration du forecast réaliste (l'opportunité dominante, son poids, et ce qui se "
    "passe pour le forecast global si elle glisse ou est perdue).\n"
    "2. La concentration par étape du pipeline et le risque si les dossiers de cette étape glissent "
    "ensemble — est-ce un goulot d'étranglement dans le cycle de vente ou une simple photographie normale ?\n"
    "3. Ce que l'écart entre pessimiste et optimiste révèle sur la fiabilité du chiffre annoncé en comité.\n"
    "4. Une recommandation concrète : sur quelle opportunité ou quelle étape agir en premier cette semaine."
)

_USER_TEMPLATE = """Chiffres réels du forecast pondéré ({nb_opps} opportunités ouvertes) :
- Réaliste (somme pondérée) : {realiste} M FCFA
- Pessimiste (opportunités >= 50% de probabilité uniquement) : {pessimiste} M FCFA
- Optimiste (réaliste + moitié des deals < 50%) : {optimiste} M FCFA
- Probabilité moyenne du pipeline : {avg_prob}%
- Opportunité la plus lourde : « {top_opp_name} » ({top_opp_client}), {top_opp_share}% du forecast pondéré
- Étape la plus concentrée : {top_stage_name}, {top_stage_share}% du forecast pondéré ({top_stage_value} M FCFA)
- Écart optimiste/pessimiste : {ecart} M FCFA

Rédige l'analyse en 4 paragraphes courts, aucune invention de montant ou de nom au-delà de ceux fournis."""


def _fallback_analysis(ctx: dict) -> str:
    """Repli déterministe : mêmes constats que l'ancien template JS, sur les vraies données."""
    return "\n\n".join([
        f"Le scénario réaliste ({ctx['realiste']} M FCFA) est concentré : la seule opportunité "
        f"« {ctx['top_opp_name']} » ({ctx['top_opp_client']}) pèse pour {ctx['top_opp_share']}% du total "
        "pondéré. Une seule signature ou un seul retard sur ce dossier suffit à faire bouger le forecast global.",
        f"L'étape « {ctx['top_stage_name']} » concentre à elle seule {ctx['top_stage_share']}% du forecast "
        f"pondéré ({ctx['top_stage_value']} M FCFA) — une concentration à surveiller si ces dossiers glissent "
        "tous au même moment.",
        f"Écart entre les scénarios : {ctx['ecart']} M FCFA séparent le pessimiste et l'optimiste, ce qui "
        f"reflète la probabilité moyenne encore incertaine ({ctx['avg_prob']}%) sur l'échantillon de "
        f"{ctx['nb_opps']} opportunités réelles du pipeline.",
        f"Recommandation : sécuriser d'abord « {ctx['top_opp_name']} » ({ctx['top_opp_client']}) — c'est "
        "elle qui fait bouger le forecast le plus, avant de traiter les dossiers de l'étape "
        f"« {ctx['top_stage_name']} ».",
    ])


async def build_forecast_analysis(llm, ctx: dict) -> str:
    """ctx : faits déjà calculés par aggregation.py (jamais recalculé par le LLM)."""
    if llm is None:
        return _fallback_analysis(ctx)
    try:
        user = _USER_TEMPLATE.format(**ctx)
        text = await llm.generate(system=_SYSTEM, user=user, max_tokens=800, temperature=0.5)
        return (text or "").strip() or _fallback_analysis(ctx)
    except Exception as exc:
        logger.warning("Analyse IA forecast échouée (repli calculs réels) : %s", exc)
        return _fallback_analysis(ctx)
