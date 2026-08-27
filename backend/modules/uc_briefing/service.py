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

from modules.uc_briefing import facts, preferences, seuils as seuils_mod, store
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

# Un verrou par rôle : deux relances rapprochées depuis l'écran Réglages
# lanceraient sinon deux générations concurrentes qui s'écraseraient l'une
# l'autre dans store.save. Même motif que uc_daily_analysis.store._lock_for.
_REFRESH_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(role: str) -> asyncio.Lock:
    lock = _REFRESH_LOCKS.get(role)
    if lock is None:
        lock = _REFRESH_LOCKS[role] = asyncio.Lock()
    return lock


async def _build_section(role: str, crm, llm, composition: facts.Composition | None = None) -> dict:
    built = await _FACTS_BUILDERS[role](crm, composition)
    action = built.get("action")
    consigne = composition.consigne if composition else ""
    pilote = composition.pilote if composition else False
    # Résumé (tête de cockpit) et analyse (lecture longue) portent sur les mêmes
    # faits mais ne servent pas le même usage : générés en parallèle, ce job
    # tournant de nuit, sa latence n'est pas vue par l'utilisateur.
    # `blocs` accompagne les puces jusqu'à la rédaction mais N'ENTRE PAS dans la
    # section stockée : il ne porte rien que `bullets` n'ait déjà, et le contrat
    # lu par les cockpits (facts / bullets / resume / action / analysis) n'a
    # aucune raison de s'élargir pour un besoin interne au prompt.
    blocs = built.get("blocs")
    resume, analysis = await asyncio.gather(
        build_brief_resume(llm, role, built["bullets"], action,
                           consigne=consigne, pilote=pilote, blocs=blocs),
        build_daily_analysis(llm, role, built["bullets"],
                             consigne=consigne, pilote=pilote, blocs=blocs),
    )
    return {
        "facts": built["facts"],
        "bullets": built["bullets"],
        "action": action,
        "resume": resume,
        "analysis": analysis,
    }


def _composition_depuis(document: dict | None,
                       seuils: dict[str, float] | None = None) -> facts.Composition:
    """Traduit un document de préférences en composition exploitable par facts.

    Rien de coché + consigne posée = mode « consigne pilote » : tout le
    catalogue du rôle est activé (ids=None) pour que l'IA puisse piocher, et le
    drapeau `pilote` fait basculer narratif sur le bloc de prompt où la
    consigne choisit le CONTENU. Le cockpit n'y perd rien : `facts` devient un
    sur-ensemble, jamais un sous-ensemble (DgVision lit facts.ca_ytd_xof).

    Le test est `elements == []` et non `not elements` : `None` signifie
    « aucune préférence » (tout actif, mode normal) et doit le rester.
    """
    doc = document or {}
    elements = doc.get("elements")
    consigne = doc.get("consigne", "")
    if elements == [] and consigne.strip():
        return facts.Composition(None, consigne, pilote=True, seuils=seuils)
    return facts.Composition(elements, consigne, seuils=seuils)


async def generate(crm, llm, triggered_by: str = "schedule") -> dict:
    """Calcule les 5 sections en parallèle et remplace le snapshot gelé."""
    # Un seul SELECT pour les cinq rôles, avant le gather : un `load` par section
    # ferait cinq requêtes dans un contexte où les erreurs sont avalées.
    documents = await preferences.load_all()
    # Un seul SELECT pour les seuils des cinq rôles, au même titre que les
    # préférences : les builders les lisent au fil du calcul et ne doivent pas
    # toucher la base eux-mêmes (cf. facts.Composition.seuil).
    tous_seuils = await seuils_mod.charger_tous()
    compositions = {
        role: _composition_depuis(documents.get(role), tous_seuils.get(role))
        for role in ROLES
    }
    results = await asyncio.gather(
        *(_build_section(role, crm, llm, compositions[role]) for role in ROLES),
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

    maintenant = datetime.now(timezone.utc).isoformat()
    for section in sections.values():
        # Fraîcheur PAR section : une régénération d'un seul rôle ne touche pas
        # l'horodatage global, l'écran a besoin de savoir quand SA section a été
        # calculée (cf. generate_role).
        section["generated_at"] = maintenant
        section["triggered_by"] = triggered_by

    payload = {
        "generated_at": maintenant,
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


async def generate_role(role: str, crm, llm, triggered_by: str = "manual") -> dict:
    """Régénère UNE section et la fusionne dans le snapshot existant.

    `store.save` réécrit le fichier en entier : les quatre autres sections sont
    donc relues puis recopiées telles quelles. Sans cette relecture, régénérer le
    DG effacerait les briefings des autres rôles jusqu'au cron de minuit — une
    perte que personne ne verrait avant le lendemain matin.

    `generated_at` racine n'est PAS touché : il date le dernier run COMPLET, et
    l'écraser ferait croire que les cinq sections datent de l'instant. C'est
    `sections[role]["generated_at"]` qui porte la fraîcheur de cette section.
    """
    if role not in ROLES:
        raise ValueError(f"Rôle inconnu : {role}")

    async with _lock_for(role):
        composition = _composition_depuis(
            await preferences.load(role), await seuils_mod.charger(role)
        )
        section = await _build_section(role, crm, llm, composition)
        section["generated_at"] = datetime.now(timezone.utc).isoformat()
        section["triggered_by"] = triggered_by

        payload = store.load() or {
            "generated_at": None, "triggered_by": None, "sections": {}, "sections_en_echec": [],
        }
        payload.setdefault("sections", {})[role] = section
        payload["sections_en_echec"] = [
            r for r in payload.get("sections_en_echec", []) if r != role
        ]
        store.save(payload)

    logger.info(
        "Briefing du rôle '%s' régénéré (%s) : %d puce(s)",
        role, triggered_by, len(section.get("bullets", [])),
    )
    return section
