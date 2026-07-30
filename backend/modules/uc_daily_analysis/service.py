"""Génération quotidienne des 7 narrations de cockpit — appelée par le job du
matin (après la sync Odoo) et par la relance manuelle.

Une section en échec n'abandonne pas les autres : elle est simplement absente
de la base pour la journée, et le premier affichage de cockpit la recalculera en
secours (cf. store.daily_cached). Même principe de dégradation partielle que
uc_briefing/service.py.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from modules.uc_daily_analysis import computations as comp
from modules.uc_daily_analysis import store

logger = logging.getLogger(__name__)


async def _trend(crm, llm) -> tuple[str, str, dict]:
    """La tendance est la seule narration paramétrée par ce que la vue affiche :
    on reconstitue ici la même courbe que le cockpit DG pour figer la narration
    sous la variante qu'il demandera."""
    months, values = await comp.trend_inputs(crm, datetime.now().year)
    payload = await comp.trend_analysis(llm, months, values)
    return comp.KEY_TREND, comp.trend_variant(months), payload


async def _performance(crm, llm):
    return comp.KEY_PERFORMANCE, "", await comp.performance_analysis(crm, llm)


async def _forecast(crm, llm):
    return comp.KEY_FORECAST, "", await comp.forecast_analysis(crm, llm)


async def _margins(crm, llm):
    # Variante vide : les cockpits DF et DO demandent les marges sans filtre
    # d'exercice. Un appel explicite sur une autre année reste possible, il
    # passera par le calcul de secours et sera figé sous sa propre variante.
    return comp.KEY_MARGINS, comp.margins_variant(None), await comp.margins_analysis(crm, llm)


async def _unpaid(crm, llm):
    return comp.KEY_UNPAID, "", await comp.unpaid_analysis(crm, llm)


async def _crosssell(crm, llm):
    return comp.KEY_CROSSSELL, "", await comp.crosssell_analysis(crm, llm)


async def _partners(crm, llm):
    return comp.KEY_PARTNERS, "", await comp.partners_analysis(crm, llm)


# `_trend` est volontairement ABSENT : la tuile « Lecture de la trajectoire » du
# cockpit DG est commentée dans la vue (DgVision.tsx), personne ne lit donc cette
# narration — la générer chaque matin serait un appel Sonnet quotidien pour rien.
# Son endpoint reste figé à la journée : si la tuile est réactivée, le premier
# affichage du jour la calcule et les suivants relisent la base. Pour supprimer
# aussi ce premier chargement, remettre `_trend` dans ce tuple.
SECTIONS = (_performance, _forecast, _margins, _unpaid, _crosssell, _partners)


async def generate_all(crm, llm, triggered_by: str = "schedule") -> dict:
    """Recalcule les 7 narrations et remplace celles du jour.

    Les 7 partent en parallèle : ce job tourne hors présence utilisateur, sa
    latence cumulée (7 × 10-20 s en séquentiel) n'a aucune raison d'être subie.
    """
    results = await asyncio.gather(*(section(crm, llm) for section in SECTIONS),
                                   return_exceptions=True)

    figees: list[str] = []
    ignorees: list[dict] = []
    for section, res in zip(SECTIONS, results):
        nom = section.__name__.lstrip("_")
        if isinstance(res, Exception):
            logger.warning("Analyse quotidienne '%s' en échec : %s", nom, res)
            ignorees.append({"section": nom, "raison": f"erreur: {res}"})
            continue

        key, variant, payload = res
        if not store.est_figeable(payload):
            # Repli déterministe ou absence de données : ne rien figer, le
            # cockpit réessaiera au premier affichage.
            ignorees.append({"section": nom, "raison": payload.get("source", "inconnue")})
            continue

        await store.save(key, variant, payload, triggered_by)
        figees.append(key)

    purgees = await store.purge_anciennes()
    logger.info(
        "Analyses quotidiennes (%s) : %d figée(s) %s, %d ignorée(s), %d ancienne(s) purgée(s)",
        triggered_by, len(figees), figees, len(ignorees), purgees,
    )
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "triggered_by": triggered_by,
        "figees": figees,
        "ignorees": ignorees,
    }
