"""Rédaction du profil client (activité + recommandations) par Claude, à
partir des agrégats réels et des signaux déjà détectés (aggregation.py) —
jamais recalculés ni inventés par le LLM. Repli déterministe si Claude échoue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es directeur commercial d'une ESN ivoirienne (S2I). Tu prépares la fiche d'un compte pour "
    "l'account manager qui s'en occupe, à partir de ses vrais agrégats commerciaux (dossiers, CA, "
    "backlog) et des constats déjà détectés — jamais inventés. Réponds STRICTEMENT en JSON, sans texte "
    "autour."
)

_USER_TEMPLATE = """Client : {client}
Nombre de dossiers : {nb_dossiers}
CA cumulé (provisoire + définitif) : {ca_m} M FCFA
Backlog non facturé : {backlog_m} M FCFA
Reste à encaisser : {reste_m} M FCFA
Dernier projet connu : {dernier_projet}
Constats déjà détectés : {constats}

Réponds avec ce JSON :
{{"activite": "3 phrases : (1) la taille et la régularité réelles de la relation — dire ce que les chiffres signifient (compte stratégique, ponctuel, en croissance ?), pas les répéter, (2) ce que le backlog et le reste à encaisser révèlent sur la santé financière de la relation, (3) le point qui devrait orienter la préparation du prochain rendez-vous avec ce client", "recommandations": ["2 à 3 actions concrètes et datées, chacune justifiée par un chiffre ou un constat précis — jamais une généralité comme « assurer le suivi »"]}}
Base-toi UNIQUEMENT sur les chiffres et constats donnés, aucune invention de montant ou de fait."""


def _fallback_profile(ctx: dict) -> dict:
    constats = ctx["constats_list"]
    activite = (
        f"{ctx['nb_dossiers']} dossiers pour {ctx['ca_m']} M FCFA de CA cumulé, "
        f"{ctx['backlog_m']} M FCFA de backlog non facturé et {ctx['reste_m']} M FCFA restant à encaisser"
        + (f" — dernier projet : {ctx['dernier_projet']}." if ctx["dernier_projet"] else ".")
    )
    recommandations = constats if constats else ["Aucun signal particulier détecté sur ce compte."]
    return {"activite": activite, "recommandations": recommandations, "ai_generated": False}


async def build_client_profile(llm, ctx: dict) -> dict:
    if llm is None:
        return _fallback_profile(ctx)
    try:
        import json
        user = _USER_TEMPLATE.format(
            client=ctx["client"],
            nb_dossiers=ctx["nb_dossiers"],
            ca_m=ctx["ca_m"],
            backlog_m=ctx["backlog_m"],
            reste_m=ctx["reste_m"],
            dernier_projet=ctx["dernier_projet"] or "non renseigné",
            constats="; ".join(ctx["constats_list"]) or "aucun",
        )
        raw = await llm.generate(system=_SYSTEM, user=user, max_tokens=750, temperature=0.4)
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0]
        data = json.loads(raw)
        activite = str(data.get("activite") or "").strip()
        recos = data.get("recommandations")
        if not activite or not isinstance(recos, list) or not recos:
            return _fallback_profile(ctx)
        return {"activite": activite, "recommandations": [str(r) for r in recos], "ai_generated": True}
    except Exception as exc:
        logger.warning("Profil IA client échoué pour '%s' (repli constats réels) : %s", ctx["client"], exc)
        return _fallback_profile(ctx)
