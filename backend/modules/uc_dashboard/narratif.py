"""Analyse de la courbe d'évolution du CA affichée dans le cockpit, rédigée
par Claude. Les statistiques de tendance sont déjà calculées en Python à
partir des vrais points de la courbe — Claude ne fait que les commenter et
proposer une recommandation, jamais recalculer. Repli déterministe si Claude
échoue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------- Analyse de la courbe d'évolution du CA affichée ----------
# Remplace le bouton manuel "Générer une projection" : se déclenche
# automatiquement à chaque changement de période, sur les points RÉELS de la
# courbe affichée (jamais les 2 mois de prévision ajoutés au graphe).

_SYSTEM_TREND = (
    "Tu es directeur commercial d'une ESN ivoirienne (S2I) qui s'adresse à la Direction Générale. Tu "
    "analyses la courbe d'évolution du CA commandé affichée dans le cockpit — des points déjà calculés. "
    "Une courbe n'est utile à un dirigeant que si tu dis ce qui l'explique probablement et ce qu'il faut "
    "surveiller ensuite — pas juste si elle monte ou descend.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. La tendance réelle et son ampleur (pas seulement hausse/baisse : de combien, et est-ce régulier "
    "ou porté par un ou deux mois exceptionnels comme le pic ou le creux fournis ?).\n"
    "2. Une hypothèse sur ce qui pourrait l'expliquer, formulée comme une question à vérifier plutôt "
    "qu'un fait — tu n'as pas accès aux causes, seulement aux chiffres.\n"
    "3. Une recommandation concrète : quoi surveiller ou faire vérifier avant la prochaine clôture."
)

_USER_TEMPLATE_TREND = """Courbe CA commandé affichée ({nb_mois} mois, de {periode_debut} à {periode_fin}) :
- Valeur en {periode_debut} : {valeur_debut} M FCFA
- Valeur en {periode_fin} : {valeur_fin} M FCFA
- Variation sur la période affichée : {variation_pct}%
- Pic : {mois_pic} ({valeur_pic} M FCFA)
- Creux : {mois_creux} ({valeur_creux} M FCFA)
- Moyenne sur la période affichée : {moyenne_periode} M FCFA

Rédige l'analyse en 3 paragraphes courts, aucune invention de montant ou de mois au-delà de ceux fournis."""


def _fallback_trend(ctx: dict) -> str:
    """Repli déterministe sur les vraies données de la courbe affichée."""
    variation = ctx["variation_pct"]
    tendance = "en hausse" if variation > 0 else "en baisse" if variation < 0 else "stable"
    amplitude = ctx["valeur_pic"] - ctx["valeur_creux"]
    return "\n\n".join([
        f"Le CA commandé est {tendance} entre {ctx['periode_debut']} ({ctx['valeur_debut']} M FCFA) et "
        f"{ctx['periode_fin']} ({ctx['valeur_fin']} M FCFA), soit {variation}% sur la période affichée. "
        f"Le pic se situe en {ctx['mois_pic']} ({ctx['valeur_pic']} M FCFA), le creux en "
        f"{ctx['mois_creux']} ({ctx['valeur_creux']} M FCFA) — un écart de {amplitude} M FCFA entre les "
        "deux, à mettre en regard de la moyenne pour juger si la période est irrégulière.",
        f"Moyenne sur la période affichée : {ctx['moyenne_periode']} M FCFA — si {ctx['mois_pic']} ou "
        f"{ctx['mois_creux']} s'écarte fortement de cette moyenne, vérifier s'il s'agit d'un effet "
        "ponctuel (une grosse commande, une clôture décalée) avant de projeter cette tendance plus loin.",
        "Recommandation : comparer cette période à la même période de l'exercice précédent pour savoir "
        "si la variation observée est saisonnière ou structurelle avant d'ajuster le budget.",
    ])


async def build_trend_analysis(llm, ctx: dict) -> str:
    """ctx : statistiques de la courbe déjà calculées en Python (jamais recalculées par le LLM)."""
    if llm is None:
        return _fallback_trend(ctx)
    try:
        user = _USER_TEMPLATE_TREND.format(**ctx)
        text = await llm.generate(system=_SYSTEM_TREND, user=user, max_tokens=750, temperature=0.5)
        return (text or "").strip() or _fallback_trend(ctx)
    except Exception as exc:
        logger.warning("Analyse IA tendance CA échouée (repli calculs réels) : %s", exc)
        return _fallback_trend(ctx)


# ---------- Analyse marge provisoire vs définitive (backlog / érosion) ----------
# Comble le seul thème sans narratif dédié pour DO/DF : le décalage entre la
# valorisation initiale d'un dossier (provisoire) et sa réalité facturée
# (définitif), déjà calculé par LocalCRMAdapter.get_margin_stats().

_SYSTEM_MARGINS = (
    "Tu es directeur administratif et financier d'une ESN ivoirienne (S2I). Tu commentes l'écart entre "
    "la marge provisoire (valorisation initiale d'un dossier) et la marge définitive (réalité facturée à "
    "date) sur l'ensemble des dossiers actifs — un signal d'alerte précoce si l'écart est défavorable, "
    "bien avant que la perte n'apparaisse en clôture comptable.\n\n"
    "Structure attendue, en français, sans titres ni markdown :\n"
    "1. Ce que l'écart entre marge provisoire moyenne et marge définitive moyenne révèle sur la fiabilité "
    "des devis initiaux — un écart défavorable large et généralisé n'est pas la même alerte qu'un écart "
    "concentré sur un seul gros dossier.\n"
    "2. Le taux de matérialisation du CA (définitif rapporté au provisoire) et ce qu'il indique sur le "
    "rythme réel de facturation du backlog.\n"
    "3. Le dossier le plus dégradé identifié et une recommandation concrète : renégocier le devis, "
    "vérifier le staffing, ou accepter l'écart comme normal en cours de projet."
)

_USER_TEMPLATE_MARGINS = """Chiffres réels sur l'ensemble des dossiers actifs ({nb_dossiers} dossiers) :
- Backlog non facturé : {backlog_m} M FCFA
- Taux de matérialisation du CA (définitif / provisoire) : {taux_materialisation}%
{bloc_marge}
- Dossier le plus dégradé : {pire_dossier_ref} ({pire_dossier_client}), marge définitive {pire_dossier_marge}%

Rédige l'analyse en 3 paragraphes courts, aucune invention de chiffre ou de nom au-delà de ceux fournis."""


def _bloc_marge(ctx: dict) -> str:
    """Les lignes « marge » du prompt, rendues selon que le taux définitif est
    exploitable ou non.

    Un dossier sans dépense imputée affiche 100 % de marge par construction. Sur
    un exercice où l'imputation ne couvre que 0,5 % du CA — c'est le cas de 2026
    sur ce miroir — il n'y a pas de marge définitive à commenter, et un LLM à qui
    on sert « 99,99 % » commentera une performance exceptionnelle. La consigne
    « aucune invention au-delà des chiffres fournis » ne protège que si les
    chiffres fournis sont vrais : c'est ici que ça se joue, pas dans le système.
    """
    lignes = [f"- Marge provisoire (marge / CA provisoire) : {ctx.get('marge_provisoire_pct')}%"]
    if ctx.get("marge_definitive_exploitable"):
        lignes += [
            f"- Marge définitive (périmètre à dépense imputée) : {ctx.get('marge_definitive_pct')}%",
            f"- Écart marge définitive − provisoire : {ctx.get('ecart_marge_pts')} points",
        ]
    else:
        lignes.append(
            "- Marge définitive : NON MESURABLE sur cette période — la dépense n'est "
            f"imputée que sur {ctx.get('couverture_marge_pct')}% du CA facturé. "
            "Ne commente aucune marge définitive et ne l'estime pas : dis que la "
            "donnée manque, et pourquoi."
        )
    return "\n".join(lignes)


def _fallback_margins(ctx: dict) -> str:
    # Même verdict de mesurabilité que le gabarit ci-dessus : sans marge
    # définitive, le premier paragraphe dit ce qui manque au lieu de chiffrer un
    # écart contre un taux qui n'existe pas (et `abs(None)` lèverait).
    if not ctx.get("marge_definitive_exploitable") or ctx.get("ecart_marge_pts") is None:
        return "\n\n".join([
            f"La marge définitive n'est pas mesurable sur cette période : la dépense n'est "
            f"imputée que sur {ctx.get('couverture_marge_pct')}% du CA facturé. La marge "
            f"provisoire ({ctx['marge_provisoire_pct']}%) reste, elle, mesurée sur "
            f"{ctx['nb_dossiers']} dossiers.",
            f"Le taux de matérialisation du CA ({ctx['taux_materialisation']}%) indique que le backlog "
            f"({ctx['backlog_m']} M FCFA) se facture "
            + ("plus lentement que prévu." if ctx["taux_materialisation"] < 80 else "à un rythme cohérent avec le plan."),
            f"Dossier le plus dégradé : {ctx['pire_dossier_ref']} ({ctx['pire_dossier_client']}), "
            f"marge définitive à {ctx['pire_dossier_marge']}% — à vérifier en priorité avant la prochaine clôture.",
        ])
    sens = "défavorable" if ctx["ecart_marge_pts"] < 0 else "favorable"
    return "\n\n".join([
        f"L'écart entre marge définitive ({ctx['marge_definitive_pct']}%) et marge provisoire "
        f"({ctx['marge_provisoire_pct']}%) est {sens} de {abs(ctx['ecart_marge_pts'])} points sur "
        f"{ctx['nb_dossiers']} dossiers actifs — à surveiller si cet écart se creuse d'un trimestre à l'autre.",
        f"Le taux de matérialisation du CA ({ctx['taux_materialisation']}%) indique que le backlog "
        f"({ctx['backlog_m']} M FCFA) se facture "
        + ("plus lentement que prévu." if ctx["taux_materialisation"] < 80 else "à un rythme cohérent avec le plan."),
        f"Dossier le plus dégradé : {ctx['pire_dossier_ref']} ({ctx['pire_dossier_client']}), "
        f"marge définitive à {ctx['pire_dossier_marge']}% — à vérifier en priorité avant la prochaine clôture.",
    ])


async def build_margins_analysis(llm, ctx: dict) -> str:
    """ctx : agrégats de get_margin_stats()/get_top_margin_dossiers() (jamais recalculés par le LLM)."""
    # `bloc_marge` est DÉRIVÉ ici, pas fourni par l'appelant : le gabarit et le
    # repli doivent rendre le même verdict de mesurabilité, et le calculer en un
    # seul endroit est ce qui garantit qu'ils ne peuvent pas diverger.
    ctx = {**ctx, "bloc_marge": _bloc_marge(ctx)}
    if llm is None:
        return _fallback_margins(ctx)
    try:
        user = _USER_TEMPLATE_MARGINS.format(**ctx)
        text = await llm.generate(system=_SYSTEM_MARGINS, user=user, max_tokens=750, temperature=0.5)
        return (text or "").strip() or _fallback_margins(ctx)
    except Exception as exc:
        logger.warning("Analyse IA marges échouée (repli calculs réels) : %s", exc)
        return _fallback_margins(ctx)
