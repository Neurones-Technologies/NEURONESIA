"""Persistance du module Arbitrages — registre de décisions (`decisions`),
contexte terrain (`arbitrage_contextes`) et réglages (`arbitrage_params`).
CRUD direct par session async, comme le reste du projet pour les tables
applicatives (pas de couche repository supplémentaire ici, les tables sont
simples et le module est seul à les utiliser).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import ArbitrageContexteModel, ArbitrageParamModel, DecisionModel
from modules.uc_arbitrage import conditions

logger = logging.getLogger(__name__)

# Délai de relecture par défaut d'une décision d'arbitrage. Sans date de revue
# posée à la création, `revues_en_retard` restait à 0 pour toujours et le score de
# fiabilité (module 29) ne pouvait jamais se construire : la boucle d'audit était
# décorative. 30 jours = un cycle de comité, ajustable ici.
REVIEW_DELAY_DAYS = 30


def _to_dict(d: DecisionModel) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "context": d.context,
        "decision_type": d.decision_type,
        "status": d.status,
        "owner": d.owner,
        "due_date": d.due_date.isoformat() if d.due_date else None,
        "outcome": d.outcome,
        "created_by": d.created_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "subject_ref": d.subject_ref,
        "subject_label": d.subject_label,
        "enjeu_xof": d.enjeu_xof,
        "cout_report_xof_semaine": d.cout_report_xof_semaine,
        "mandat_role": d.mandat_role,
        "profils_impliques": d.profils_impliques or [],
        "option_retenue": d.option_retenue,
        "review_date": d.review_date.isoformat() if d.review_date else None,
        "review_verdict": d.review_verdict,
        "review_comment": d.review_comment,
        "option_recommandee": d.option_recommandee or "",
        "motif_decision": d.motif_decision or "",
        "profil_payeur_classe": d.profil_payeur_classe or "",
        # La recommandation a-t-elle été suivie ? Calculé, jamais saisi. None quand
        # l'information n'existe pas (décisions antérieures à cette colonne) —
        # surtout pas False, qui se lirait comme « le mandataire a écarté la reco ».
        "reco_suivie": (
            None if not (d.option_recommandee and d.option_retenue)
            else d.option_recommandee.strip() == d.option_retenue.strip()
        ),
    }


async def create_decision(payload: dict, created_by: str) -> dict:
    now = datetime.utcnow()
    # Toute décision naît avec sa date de relecture : c'est elle qui la rend
    # vérifiable après coup (et qui alimente `revues_en_retard` + le score de
    # fiabilité). Un appelant peut la fixer explicitement, sinon +30 jours.
    review_date = _parse_dt(payload.get("review_date")) or now + timedelta(days=REVIEW_DELAY_DAYS)
    status = payload.get("status") or "en_cours"
    async with AsyncSessionLocal() as session:
        decision = DecisionModel(
            title=payload["title"],
            context=payload.get("context", ""),
            decision_type=payload.get("decision_type", "ARBITRAGE"),
            owner=payload.get("owner", created_by),
            due_date=_parse_dt(payload.get("due_date")) or review_date,
            review_date=review_date,
            created_by=created_by,
            created_at=now,
            subject_ref=payload.get("subject_ref", ""),
            subject_label=payload.get("subject_label", ""),
            enjeu_xof=float(payload.get("enjeu_xof") or 0),
            cout_report_xof_semaine=float(payload.get("cout_report_xof_semaine") or 0),
            mandat_role=payload.get("mandat_role", ""),
            profils_impliques=payload.get("profils_impliques", []),
            option_retenue=payload.get("option_retenue", ""),
            option_recommandee=payload.get("option_recommandee", ""),
            motif_decision=payload.get("motif_decision", ""),
            profil_payeur_classe=payload.get("profil_payeur_classe", ""),
            status=status,
            # Une décision créée directement tranchée doit porter sa date de
            # décision : `update_decision` ne la pose que sur transition, et le
            # registre affichait donc des décisions tranchées sans date.
            decided_at=now if status == "tranchee" else None,
        )
        session.add(decision)
        await session.commit()
        await session.refresh(decision)
        return _to_dict(decision)


async def list_decisions(status: str | None = None, subject_ref: str | None = None) -> list[dict]:
    async with AsyncSessionLocal() as session:
        q = select(DecisionModel).order_by(DecisionModel.created_at.desc())
        if status:
            q = q.where(DecisionModel.status == status)
        if subject_ref:
            q = q.where(DecisionModel.subject_ref == subject_ref)
        result = await session.execute(q)
        return [_to_dict(d) for d in result.scalars()]


async def get_decision(decision_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        decision = await session.get(DecisionModel, decision_id)
        return _to_dict(decision) if decision else None


async def update_decision(decision_id: int, patch: dict) -> dict | None:
    """Trancher / reporter / escalader une décision, ou enregistrer sa revue."""
    async with AsyncSessionLocal() as session:
        decision = await session.get(DecisionModel, decision_id)
        if decision is None:
            return None

        if "status" in patch:
            decision.status = patch["status"]
            if patch["status"] == "tranchee" and decision.decided_at is None:
                decision.decided_at = datetime.utcnow()
        if "outcome" in patch:
            decision.outcome = patch["outcome"]
        if "motif_decision" in patch:
            decision.motif_decision = patch["motif_decision"]
        if "option_retenue" in patch:
            decision.option_retenue = patch["option_retenue"]
        if "due_date" in patch:
            decision.due_date = _parse_dt(patch["due_date"])
        if "review_date" in patch:
            decision.review_date = _parse_dt(patch["review_date"])
        if "review_verdict" in patch:
            decision.review_verdict = patch["review_verdict"]
        if "review_comment" in patch:
            decision.review_comment = patch["review_comment"]

        await session.commit()
        await session.refresh(decision)
        return _to_dict(decision)


async def reliability_stats() -> dict:
    """Fiabilité des recommandations — cf. module 29 du mockup.

    Deux taux distincts, et non un seul : le taux de SUIVI (les mandataires
    retiennent-ils l'option recommandée ?) et le taux de CONFIRMATION (quand ils
    la retiennent, se vérifie-t-elle ?). Le second n'était pas interprétable
    seul : une décision où le mandataire avait écarté la recommandation puis
    réussi y était comptée comme une recommandation vérifiée, ce qui gonflait le
    score de l'outil avec le mérite de l'humain qui l'avait contredit.

    Historique volontairement affiché comme insuffisant tant que le nombre de
    décisions revues reste faible : pas de score fabriqué sur peu de données.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DecisionModel).where(DecisionModel.review_verdict != "")
        )
        reviewed = list(result.scalars())
        tracked = list((await session.execute(
            select(DecisionModel).where(DecisionModel.option_recommandee != "")
        )).scalars())

    total = len(reviewed)
    confirmed = sum(1 for d in reviewed if d.review_verdict == "confirme")

    # Taux de suivi : calculable dès qu'une décision porte la recommandation de
    # l'époque, sans attendre sa revue — c'est le signal le plus précoce sur
    # l'utilité perçue de l'outil.
    nb_suivies = sum(
        1 for d in tracked
        if d.option_retenue and d.option_recommandee.strip() == d.option_retenue.strip()
    )
    nb_tracked = len(tracked)

    # Confirmation restreinte aux décisions où la recommandation a effectivement
    # été suivie : les seules qui disent quelque chose sur l'outil.
    suivies_revues = [
        d for d in reviewed
        if d.option_recommandee and d.option_retenue
        and d.option_recommandee.strip() == d.option_retenue.strip()
    ]
    confirmees_suivies = sum(1 for d in suivies_revues if d.review_verdict == "confirme")

    return {
        "nb_decisions_revues": total,
        "nb_confirmees": confirmed,
        "taux_confirmation_pct": round(confirmed / total * 100, 1) if total else None,
        "historique_suffisant": total >= 5,
        "nb_decisions_tracees": nb_tracked,
        "nb_reco_suivies": nb_suivies,
        "taux_suivi_pct": round(nb_suivies / nb_tracked * 100, 1) if nb_tracked else None,
        "nb_suivies_revues": len(suivies_revues),
        "taux_confirmation_reco_suivie_pct": (
            round(confirmees_suivies / len(suivies_revues) * 100, 1) if suivies_revues else None
        ),
        "note": (
            f"{total} décision(s) revue(s) à ce jour."
            if total >= 5 else
            f"Seulement {total} décision(s) revue(s) — historique insuffisant pour un taux fiable (seuil : 5)."
        ),
        "note_suivi": (
            f"{nb_suivies} recommandation(s) suivie(s) sur {nb_tracked} décision(s) tracée(s)."
            if nb_tracked else
            "Aucune décision ne porte encore la recommandation de l'outil : le taux de suivi se "
            "construira à partir des prochaines."
        ),
    }


# ─── Contexte terrain (contribution du commercial du compte) ──────────────────


def _contexte_to_dict(c: ArbitrageContexteModel) -> dict:
    return {
        "id": c.id,
        "subject_ref": c.subject_ref,
        "motif_retard": c.motif_retard,
        "dossier_toujours_actif": c.dossier_toujours_actif,
        "created_by": c.created_by,
        "created_role": c.created_role,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


async def add_contexte(subject_ref: str, payload: dict, created_by: str, created_role: str) -> dict:
    """Ajoute une contribution terrain à un dossier. Jamais de mise à jour en
    place : les contributions s'empilent. Si l'account manager disait en mars
    « attente de mandatement » et en juin « litige ouvert sur la prestation »,
    écraser la première effacerait le fait que la situation a changé — c'est
    exactement ce qu'une revue à échéance a besoin de pouvoir relire."""
    async with AsyncSessionLocal() as session:
        contexte = ArbitrageContexteModel(
            subject_ref=subject_ref,
            motif_retard=(payload.get("motif_retard") or "").strip(),
            dossier_toujours_actif=(payload.get("dossier_toujours_actif") or "").strip(),
            created_by=created_by,
            created_role=created_role,
            created_at=datetime.utcnow(),
        )
        session.add(contexte)
        await session.commit()
        await session.refresh(contexte)
        return _contexte_to_dict(contexte)


async def list_contextes(subject_ref: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArbitrageContexteModel)
            .where(ArbitrageContexteModel.subject_ref == subject_ref)
            .order_by(ArbitrageContexteModel.created_at.desc())
        )
        return [_contexte_to_dict(c) for c in result.scalars()]


# ─── Conditions d'entrée en arbitrage (activation par profil) ─────────────────

# Clé unique de la table `arbitrage_params`. Le contenu est
# `{"<profil>": ["<code de condition>", ...]}` — jamais les conditions
# elles-mêmes, qui vivent dans `conditions.py` (cf. sa docstring).
CLE_CONDITIONS = "conditions_par_profil"


async def get_conditions_par_profil() -> dict[str, list[str]]:
    """Réglage de tous les profils, filtré des codes que le backend n'implémente
    pas.

    L'absence de ligne, un JSON illisible ou un profil absent valent tous
    « aucune condition active » : le réglage ne peut pas casser la file, au pire
    il ne s'applique pas. Sur un module dont la promesse est de dire pourquoi un
    dossier est là, une file vide par accident de configuration serait le pire
    mode de panne possible.
    """
    async with AsyncSessionLocal() as session:
        row = await session.get(ArbitrageParamModel, CLE_CONDITIONS)
        brut = row.value_json if row else "{}"

    try:
        charge = json.loads(brut or "{}")
    except (TypeError, ValueError):
        logger.warning("Réglage « %s » illisible en base — ignoré.", CLE_CONDITIONS)
        charge = {}
    if not isinstance(charge, dict):
        return {}

    return {
        profil: conditions.normaliser(codes)
        for profil, codes in charge.items()
        if profil in conditions.PROFILS_PARAMETRABLES
    }


async def get_conditions_profil(profil: str | None) -> list[str]:
    """Conditions actives d'un profil. Un profil absent, inconnu ou vide (job de
    nuit, briefing, admin) n'active rien : la file reste celle du socle."""
    if not profil:
        return []
    return (await get_conditions_par_profil()).get(profil, [])


async def set_conditions_profil(profil: str, codes, updated_by: str) -> dict[str, list[str]]:
    """Enregistre le réglage d'un profil et renvoie l'état complet après écriture.

    Les codes inconnus sont écartés à l'écriture, pas seulement à la lecture :
    la base ne conserve que ce que le backend sait appliquer, ce qui évite qu'un
    réglage périmé donne l'illusion d'un filtre encore actif.
    """
    retenus = conditions.normaliser(codes)
    async with AsyncSessionLocal() as session:
        row = await session.get(ArbitrageParamModel, CLE_CONDITIONS)
        try:
            charge = json.loads(row.value_json or "{}") if row else {}
        except (TypeError, ValueError):
            charge = {}
        if not isinstance(charge, dict):
            charge = {}

        charge[profil] = retenus
        charge = {
            p: c for p, c in charge.items() if p in conditions.PROFILS_PARAMETRABLES
        }

        if row is None:
            row = ArbitrageParamModel(key=CLE_CONDITIONS)
            session.add(row)
        row.value_json = json.dumps(charge, ensure_ascii=False)
        row.updated_by = updated_by
        row.updated_at = datetime.utcnow()
        await session.commit()

    return {p: conditions.normaliser(c) for p, c in charge.items()}


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
