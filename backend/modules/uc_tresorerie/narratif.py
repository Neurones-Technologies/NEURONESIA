"""Analyse qualitative de l'exposition aux impayés par Claude.

Les chiffres viennent de CRMRepository.get_unpaid_exposure() (SQL réel sur la
table invoices) — Claude ne fait que les commenter, jamais les recalculer.
Repli déterministe si Claude échoue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur financier d'une ESN ivoirienne (S2I). Tu commentes une exposition aux impayés déjà "
    "calculée pour orienter la relance de cette semaine — dire qui appeler et pourquoi, pas seulement "
    "recopier les totaux.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. Le niveau de concentration du risque (sur combien de clients repose l'essentiel de l'exposition) "
    "et ce que ça signifie pour la stratégie de relance : cibler quelques comptes ou traiter le stock "
    "dans son ensemble ?\n"
    "2. La sévérité du plus gros débiteur — son retard comparé au délai normal, et le risque si rien ne "
    "change dans les 30 prochains jours.\n"
    "3. Une recommandation concrète : qui relancer en premier, et quelle action (mise en demeure, "
    "échéancier, blocage de livraison) est proportionnée à ce niveau de retard."
)

_USER_TEMPLATE = """Chiffres réels de l'exposition aux impayés :
- Exposition totale : {exposition_totale} M FCFA sur {nb_factures} factures impayées
- Retard de plus de 90 jours : {retard_90j_montant} M FCFA sur {retard_90j_nb} factures
- Plus gros débiteur : {top_debiteur_client}, {top_debiteur_montant} M FCFA ({top_debiteur_jours} jours de retard)
- Les 3 plus gros débiteurs concentrent {top3_part_pct}% de l'exposition totale

Rédige l'analyse en 3 paragraphes courts, aucune invention de montant ou de nom au-delà de ceux fournis."""


def _fallback_analysis(ctx: dict) -> str:
    """Repli déterministe sur les vraies données."""
    return "\n\n".join([
        f"L'exposition totale aux impayés ({ctx['exposition_totale']} M FCFA sur "
        f"{ctx['nb_factures']} factures) est concentrée : les 3 plus gros débiteurs représentent à "
        f"eux seuls {ctx['top3_part_pct']}% du total — une relance ciblée sur ces trois comptes traite "
        "l'essentiel du risque, pas besoin de disperser l'effort sur tout le portefeuille.",
        f"Le débiteur le plus critique est {ctx['top_debiteur_client']} avec "
        f"{ctx['top_debiteur_montant']} M FCFA en retard depuis {ctx['top_debiteur_jours']} jours — "
        f"{ctx['retard_90j_montant']} M FCFA sont en retard de plus de 90 jours sur "
        f"{ctx['retard_90j_nb']} factures au total.",
        f"Recommandation : escalader {ctx['top_debiteur_client']} en priorité — au-delà de 90 jours, une "
        "relance simple ne suffit généralement plus ; envisager une mise en demeure formelle ou un "
        "conditionnement des prochaines livraisons.",
    ])


async def build_tresorerie_analysis(llm, ctx: dict) -> str:
    """ctx : faits déjà calculés (jamais recalculés par le LLM)."""
    if llm is None:
        return _fallback_analysis(ctx)
    try:
        user = _USER_TEMPLATE.format(**ctx)
        text = await llm.generate(system=_SYSTEM, user=user, max_tokens=750, temperature=0.5)
        return (text or "").strip() or _fallback_analysis(ctx)
    except Exception as exc:
        logger.warning("Analyse IA trésorerie échouée (repli calculs réels) : %s", exc)
        return _fallback_analysis(ctx)
