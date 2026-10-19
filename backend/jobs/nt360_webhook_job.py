"""Traitement des webhooks nt360 — idempotence et relecture.

La doc v1 fixe la conduite : « abonnez-vous aux webhooks pour être prévenu,
puis relisez l'élément concerné par son identifiant », et « un même événement
peut arriver deux fois, traitez-le de façon idempotente (clé event +
identifiant de data) ». Le contenu de `data` n'est donc JAMAIS écrit tel quel :
il sert à savoir quoi relire. Tant que les appels ne sont pas signés, c'est
aussi ce qui empêche un appel forgé d'injecter une donnée — au pire, il
déclenche la relecture d'un élément réel.

Événements (doc v1) :
- opp_won          : relecture de l'opportunité (oppId) puis de sa commande (fp).
- approval_decided : journalisé seulement — l'API n'expose aucune ressource
                     « approbations » à relire.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from adapters.nt360.nt360_adapter import Nt360Adapter
from db.database import AsyncSessionLocal
from db.models import Nt360CommandeModel, Nt360OpportuniteModel, Nt360WebhookEvenementModel

logger = logging.getLogger(__name__)

# Événement → champ de `data` qui identifie l'objet (clé d'idempotence).
EVENEMENTS = {"opp_won": "oppId", "approval_decided": "approvalId"}


def cle_evenement(event: str, data: dict) -> str | None:
    """`event:identifiant`, ou None si l'événement est inconnu ou sans identifiant."""
    champ = EVENEMENTS.get(event)
    ident = str(data.get(champ) or "").strip() if champ else ""
    return f"{event}:{ident}" if ident else None


def _ts(brut) -> datetime | None:
    try:
        return datetime.fromisoformat(str(brut).replace("Z", "+00:00")).replace(tzinfo=None) if brut else None
    except ValueError:
        return None


async def enregistrer(event: str, data: dict, ts, session_factory=None) -> str | None:
    """Journalise une réception. Rend la clé à traiter, ou None pour un doublon
    déjà traité (ou en cours). Une réception qui suit un échec est retraitée :
    c'est précisément pour cela que nt360 renvoie."""
    session_factory = session_factory or AsyncSessionLocal
    cle = cle_evenement(event, data)
    if cle is None:
        return None
    async with session_factory() as session:
        existant = await session.get(Nt360WebhookEvenementModel, cle)
        if existant is not None:
            existant.nb_receptions += 1
            a_retraiter = existant.statut == "erreur"
            if a_retraiter:
                existant.statut, existant.payload = "recu", {"event": event, "data": data, "ts": ts}
            await session.commit()
            return cle if a_retraiter else None
        session.add(Nt360WebhookEvenementModel(
            cle=cle, event=event, objet_id=cle.split(":", 1)[1], ts=_ts(ts),
            payload={"event": event, "data": data, "ts": ts},
        ))
        await session.commit()
    return cle


async def traiter(cle: str, adapter: Nt360Adapter | None, session_factory=None) -> str:
    """Relit ce que l'événement désigne et met à jour les tables nt360. Rend le statut final."""
    from jobs.nt360_sync_job import _commande, _opportunite

    session_factory = session_factory or AsyncSessionLocal

    async with session_factory() as session:
        ev = await session.get(Nt360WebhookEvenementModel, cle)
        if ev is None:
            return "inconnu"
        event, data = ev.event, (ev.payload or {}).get("data") or {}

    statut, detail = "traite", ""
    try:
        if adapter is None:
            statut, detail = "erreur", "intégration nt360 désactivée (NT360_API_KEY absente)"
        elif event == "opp_won":
            detail = await _relire_opportunite_gagnee(adapter, data, session_factory, _opportunite, _commande)
        else:
            detail = "journalisé — aucune ressource à relire pour cet événement"
    except Exception as e:
        logger.error("Webhook nt360 %s : traitement en échec : %s", cle, e, exc_info=True)
        statut, detail = "erreur", str(e)[:500]

    async with session_factory() as session:
        ev = await session.get(Nt360WebhookEvenementModel, cle)
        ev.statut, ev.detail, ev.traite_le = statut, detail, datetime.utcnow()
        await session.commit()
    logger.info("Webhook nt360 %s : %s (%s)", cle, statut, detail)
    return statut


async def _relire_opportunite_gagnee(adapter, data, session_factory, _opportunite, _commande) -> str:
    opp_id = str(data.get("oppId"))
    opp = await adapter.get("opportunities", opp_id)
    if opp is None:
        return f"opportunité {opp_id} introuvable à la relecture"
    ctx = {"fps_exclus": set(), "entite_par_fp": {}}
    morceaux = []
    async with session_factory() as session:
        ligne = _opportunite(opp, ctx, "unitaire")
        if ligne:
            await session.merge(Nt360OpportuniteModel(**ligne, synced_at=datetime.utcnow()))
            morceaux.append(f"opportunité {opp_id} relue ({ligne['stage_label'] or ligne['stage']})")
        fp = opp.get("fp") or data.get("fp")
        if fp:
            commande = await adapter.get("commandes", fp)
            if commande:
                # L'entité ne vient pas de la lecture unitaire : on garde celle
                # posée par la dernière synchro (la suivante la confirmera).
                actuelle = (await session.execute(
                    select(Nt360CommandeModel.entite).where(Nt360CommandeModel.fp == fp))).scalar()
                ctx["entite_par_fp"] = {fp: actuelle or ""}
                for r in _commande(commande, ctx):
                    await session.merge(Nt360CommandeModel(**r, synced_at=datetime.utcnow()))
                    morceaux.append(f"commande {fp} relue")
            else:
                morceaux.append(f"commande {fp} pas encore publiée")
        await session.commit()
    return " ; ".join(morceaux) or "rien à écrire (partenaire exclu)"
