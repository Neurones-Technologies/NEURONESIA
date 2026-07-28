"""Analyse fournisseurs rédigée par Claude, à partir des vrais agrégats
(purchase_orders) — jamais recalculés par le LLM. Repli déterministe si Claude
échoue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur des opérations d'une ESN ivoirienne (S2I). Tu commentes l'exposition aux "
    "fournisseurs déjà calculée sur les vraies commandes d'achat, pour décider si cette dépendance est "
    "un risque à traiter ou une situation normale à surveiller.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. Le niveau de concentration du risque fournisseur (sur combien de fournisseurs repose l'essentiel "
    "des achats) et ce que ça signifierait concrètement en cas de rupture chez le plus gros — délai de "
    "bascule vers un autre fournisseur, existe-t-il une alternative ?\n"
    "2. Ce que la date de dernière commande chez ce fournisseur indique sur la fraîcheur de la relation "
    "(commande récente = dépendance active, commande ancienne = dépendance qui pourrait déjà être en "
    "train de se réduire).\n"
    "3. Une recommandation concrète : négocier une clause de continuité, qualifier un second fournisseur, "
    "ou ne rien changer si la concentration reste dans une fourchette raisonnable."
)

_USER_TEMPLATE = """Chiffres réels des commandes fournisseurs :
- Montant total commandé (tous fournisseurs) : {total_m} M FCFA sur {nb_fournisseurs} fournisseurs
- Plus gros fournisseur : {top_nom}, {top_montant_m} M FCFA ({top_part_pct}% du total), {top_nb_commandes} commandes
- Dernière commande chez {top_nom} : {top_derniere_commande}

Rédige l'analyse en 3 paragraphes courts, aucune invention de montant ou de nom au-delà de ceux fournis."""


def _fallback_analysis(ctx: dict) -> str:
    return "\n\n".join([
        f"Le montant total commandé ({ctx['total_m']} M FCFA sur {ctx['nb_fournisseurs']} fournisseurs) "
        f"est concentré : {ctx['top_nom']} représente à lui seul {ctx['top_part_pct']}% du total "
        f"({ctx['top_montant_m']} M FCFA sur {ctx['top_nb_commandes']} commandes) — une rupture chez ce "
        "fournisseur toucherait une part significative des approvisionnements en cours.",
        f"Dernière commande chez {ctx['top_nom']} : {ctx['top_derniere_commande']} — une relation "
        "toujours active au vu du volume commandé.",
        f"Recommandation : sécuriser cette relation d'approvisionnement en priorité (clause de "
        f"continuité ou second fournisseur qualifié), vu son poids de {ctx['top_part_pct']}% dans le "
        "total commandé.",
    ])


async def build_partners_analysis(llm, ctx: dict) -> str:
    if llm is None:
        return _fallback_analysis(ctx)
    try:
        user = _USER_TEMPLATE.format(**ctx)
        text = await llm.generate(system=_SYSTEM, user=user, max_tokens=750, temperature=0.5)
        return (text or "").strip() or _fallback_analysis(ctx)
    except Exception as exc:
        logger.warning("Analyse IA fournisseurs échouée (repli calculs réels) : %s", exc)
        return _fallback_analysis(ctx)
