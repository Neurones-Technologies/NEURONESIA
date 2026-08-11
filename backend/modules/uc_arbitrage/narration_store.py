"""Persistance en base des rédactions LLM d'un dossier d'arbitrage.

Remplace le cache mémoire TTL 900 s de `core/services/ttl_cache.py` sur
`narratif.build_dossier_narration`, pour les mêmes raisons qui ont fait passer
les narrations de cockpit en base (cf. modules/uc_daily_analysis/store.py) :

  - le cache mémoire est process-local et l'API tourne avec `--workers 2`,
    donc chaque worker payait sa propre génération (~5 s mesurées) ;
  - il repartait de zéro à chaque redéploiement ;
  - sa fenêtre expirait même quand aucun chiffre cité n'avait bougé.

La clé est l'EMPREINTE du dossier — le sha256 de tout ce que les gabarits de
prompt consomment (`narratif._empreinte`) — et non une date : une rédaction
reste valable tant que le dossier dit la même chose, et devient inatteignable
dès qu'un montant, une lecture de payeur ou un verdict de revue change. Il n'y
a donc plus de TTL du tout, et plus de réécriture à l'identique.

Le module lit `AsyncSessionLocal` comme attribut de module — les tests le
remplacent par une fabrique sur base temporaire, comme
tests/unit/test_pipeline_snapshot_job.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from db.database import AsyncSessionLocal
from db.models import ArbitrageNarrationModel

logger = logging.getLogger(__name__)

# Rétention : une empreinte devient inatteignable dès qu'un chiffre du dossier
# bouge, donc les lignes périmées ne sont jamais relues — elles s'accumuleraient
# simplement au rythme des synchronisations Odoo. 30 jours laissent de quoi
# relire ce qui a été présenté en comité le mois écoulé.
RETENTION_JOURS = 30

# Un verrou par empreinte : deux profils ouvrant le même dossier au même instant
# déclencheraient sinon deux séries d'appels modèle identiques. Process-local,
# comme celui d'uc_daily_analysis — il ne couvre pas la course entre les deux
# workers uvicorn, qui coûte au pire une génération en double au tout premier
# affichage, jamais une incohérence (l'écriture est idempotente).
_LOCKS: dict[str, asyncio.Lock] = {}


def empreinte_hash(empreinte: tuple) -> str:
    """sha256 de l'empreinte. `default=str` couvre les valeurs non sérialisables
    qu'un champ de dossier pourrait porter un jour sans casser la clé — mieux
    vaut une clé stable et grossière qu'une exception à l'ouverture."""
    brut = json.dumps(empreinte, ensure_ascii=False, default=str)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def _lock_for(cle: str) -> asyncio.Lock:
    lock = _LOCKS.get(cle)
    if lock is None:
        lock = _LOCKS[cle] = asyncio.Lock()
    return lock


async def load(cle: str) -> dict | None:
    """Rédaction déjà enregistrée pour cette empreinte, ou None."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(ArbitrageNarrationModel).where(ArbitrageNarrationModel.empreinte == cle)
            )
        ).scalar_one_or_none()
    return dict(row.payload or {}) if row is not None else None


async def save(cle: str, subject_ref: str, payload: dict) -> None:
    """Écrit (ou remplace) la rédaction. Idempotent : deux workers qui génèrent
    la même empreinte en même temps aboutissent à une seule ligne."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ArbitrageNarrationModel).where(ArbitrageNarrationModel.empreinte == cle)
        )
        session.add(
            ArbitrageNarrationModel(
                empreinte=cle,
                subject_ref=subject_ref,
                payload=payload,
                generated_at=datetime.utcnow(),
            )
        )
        await session.commit()


async def cached_narration(
    empreinte: tuple,
    subject_ref: str,
    compute,
) -> dict:
    """Lecture de la rédaction du dossier, calculée en secours si elle manque.

    `compute` renvoie `(payload, memorisable)` : seule une rédaction
    entièrement produite par le modèle est enregistrée. Un repli déterministe
    est servi normalement mais jamais figé — sans quoi une indisponibilité de
    quelques secondes resterait en base jusqu'à ce qu'un chiffre du dossier
    change, c'est-à-dire potentiellement des jours (le cache mémoire, lui, se
    purgeait tout seul au bout de 900 s : la persistance rend ce garde-fou plus
    nécessaire, pas moins).
    """
    cle = empreinte_hash(empreinte)

    hit = await load(cle)
    if hit is not None:
        return hit

    async with _lock_for(cle):
        # Un appel concurrent a pu écrire la rédaction pendant l'attente.
        hit = await load(cle)
        if hit is not None:
            return hit

        payload, memorisable = await compute()
        if not memorisable:
            logger.info(
                "Narration d'arbitrage « %s » non mémorisée (repli déterministe)", subject_ref
            )
            return payload
        await save(cle, subject_ref, payload)
        return payload


async def purge_anciennes(retention_jours: int = RETENTION_JOURS) -> int:
    """Supprime les rédactions antérieures à la fenêtre de rétention."""
    limite = datetime.utcnow() - timedelta(days=retention_jours)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(ArbitrageNarrationModel).where(ArbitrageNarrationModel.generated_at < limite)
        )
        await session.commit()
    return result.rowcount or 0
