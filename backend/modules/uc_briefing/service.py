"""Génération du briefing quotidien : calcule les faits réels par rôle et
rédige, pour chacun, une synthèse courte par Claude — gelé dans le store
jusqu'à la prochaine régénération planifiée (minuit) ou une relance manuelle.

Une section en échec (facts ou LLM) n'abandonne pas le briefing : elle est
simplement omise de `sections`, listée dans `sections_en_echec`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from modules.uc_briefing import facts, store
from modules.uc_briefing.narratif import build_brief_resume, build_daily_analysis

logger = logging.getLogger(__name__)

ROLES = ["dg", "dir_commercial", "dir_financier", "dir_operations", "commercial"]

_FACTS_BUILDERS = {
    "dg": facts.build_dg_facts,
    "dir_commercial": facts.build_dir_commercial_facts,
    "dir_financier": facts.build_dir_financier_facts,
    "dir_operations": facts.build_dir_operations_facts,
    "commercial": facts.build_commercial_facts,
}


async def _build_section(role: str, crm, llm) -> dict:
    built = await _FACTS_BUILDERS[role](crm)
    action = built.get("action")
    # Résumé (tête de cockpit) et analyse (lecture longue) portent sur les mêmes
    # faits mais ne servent pas le même usage : générés en parallèle, ce job
    # tournant de nuit, sa latence n'est pas vue par l'utilisateur.
    resume, analysis = await asyncio.gather(
        build_brief_resume(llm, role, built["bullets"], action),
        build_daily_analysis(llm, role, built["bullets"]),
    )
    return {
        "facts": built["facts"],
        "bullets": built["bullets"],
        "action": action,
        "resume": resume,
        "analysis": analysis,
    }


async def generate(crm, llm, triggered_by: str = "schedule") -> dict:
    """Calcule les 5 sections en parallèle et remplace le snapshot gelé."""
    results = await asyncio.gather(
        *(_build_section(role, crm, llm) for role in ROLES),
        return_exceptions=True,
    )

    sections: dict = {}
    failed: list[str] = []
    for role, res in zip(ROLES, results):
        if isinstance(res, Exception):
            logger.warning("Briefing — section '%s' en échec : %s", role, res)
            failed.append(role)
        else:
            sections[role] = res

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "triggered_by": triggered_by,
        "sections": sections,
        "sections_en_echec": failed,
    }
    store.save(payload)
    logger.info(
        "Briefing quotidien généré (%s) : %d section(s), %d en échec",
        triggered_by, len(sections), len(failed),
    )
    return payload
