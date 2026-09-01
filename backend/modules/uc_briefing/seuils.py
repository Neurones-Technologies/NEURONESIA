"""Seuils d'alerte du briefing, réglables par rôle — le troisième mécanisme.

C'est ce qui permet au MÊME moteur de faits de servir quatre briefings
différents. Jusqu'ici les seuils vivaient en dur dans `facts.py` : 50 % de
concentration, 80 % de matérialisation, 60 jours de fenêtre d'échéance. Deux
conséquences, l'une visible et l'autre pas :

  - déplacer un seuil coûtait un déploiement ;
  - le DG et le DAF s'alertaient au même endroit sur la même donnée, alors que
    ce n'est pas le même métier. 90 jours de retard, c'est du contentieux pour
    la DAF et un signal de rupture commerciale pour la DG bien avant.

DOCTRINE — un seuil n'entre ici que s'il COMMANDE une phrase du briefing. Un
nombre qui ne change aucune formulation n'est pas un seuil, c'est un réglage
d'affichage, et il n'a rien à faire dans un écran de direction.

Portée par RÔLE et non par utilisateur, exactement comme
`uc_briefing.preferences` : le briefing est généré par rôle, un seuil par
personne imposerait autant de générations que de comptes. `updated_by` est la
contrepartie obligatoire d'un réglage partagé.

Table vide = les défauts ci-dessous s'appliquent, à l'identique du comportement
d'avant cette fonctionnalité. Rien à migrer, rien à initialiser.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import BriefingSeuilModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Seuil:
    """`effet` dit ce que le seuil DÉCLENCHE, pas ce qu'il mesure.

    C'est la seule description utile à qui règle : personne ne déplace « le seuil
    de concentration », on déplace « le moment où le briefing dit que le
    portefeuille est trop concentré ».
    """
    cle: str
    libelle: str
    unite: str          # pct | jours | xof | nb
    defaut: float
    mini: float
    maxi: float
    effet: str


# ── Catalogue commun ─────────────────────────────────────────────────────────
# Un seuil peut servir plusieurs rôles avec des valeurs différentes : la
# définition est unique, la valeur est par rôle (cf. DEFAUTS).
CATALOGUE: dict[str, Seuil] = {s.cle: s for s in [
    Seuil("concentration_top5_pct", "Concentration du top 5", "pct", 50, 10, 100,
          "Au-delà, le briefing signale que le portefeuille dépend d'un trop petit "
          "nombre de comptes."),
    Seuil("materialisation_pct", "Matérialisation du CA", "pct", 80, 10, 100,
          "En dessous, le briefing alerte : trop de CA provisoire ne devient jamais "
          "définitif."),
    Seuil("dormance_jours", "Silence sur une opportunité", "jours", 15, 3, 180,
          "Une affaire encore dans les temps mais sans retouche depuis ce délai entre "
          "dans la liste « à relancer »."),
    Seuil("echeance_fenetre_jours", "Fenêtre des échéances à venir", "jours", 60, 7, 180,
          "Horizon des opportunités dont la clôture est annoncée comme imminente."),
    Seuil("retard_relance_jours", "Retard déclenchant une relance", "jours", 30, 1, 180,
          "Une facture échue depuis ce délai entre dans les relances du jour."),
    Seuil("contentieux_jours", "Retard réputé contentieux", "jours", 90, 30, 365,
          "Au-delà, l'impayé n'est plus présenté comme un retard mais comme une créance "
          "qui ne rentrera pas seule."),
    Seuil("rupture_silence_jours", "Silence d'un compte majeur", "jours", 180, 30, 730,
          "Un client sans commande depuis ce délai est signalé en rupture de rythme."),
    Seuil("delta_significatif_xof", "Variation digne d'être citée", "xof", 1_000_000, 0, 1e12,
          "En dessous, une variation quotidienne est traitée comme du bruit et le "
          "briefing dit « stable » plutôt que d'afficher un mouvement."),
    Seuil("visibilite_mois_min", "Visibilité minimale du carnet", "nb", 3, 1, 24,
          "En dessous, le briefing alerte : le backlog ne couvre plus assez de mois de "
          "facturation."),
    Seuil("book_to_bill_min", "Book-to-bill plancher", "nb", 1.0, 0.1, 5,
          "En dessous de 1, l'entreprise facture plus vite qu'elle ne remplit son "
          "carnet — le briefing le signale."),
]}

# Valeurs par défaut PAR RÔLE. Un rôle absent d'une clé prend le défaut du
# catalogue. Les écarts ci-dessous sont des choix métier, pas des oublis :
#   - la DAF relance à 30 j (délai de gestion), la DG ne veut voir un impayé que
#     lorsqu'il devient structurel ;
#   - un commercial travaille à 30 jours d'horizon, un directeur commercial à 60 ;
#   - le DG s'alarme d'un silence client plus tôt que la production.
DEFAUTS: dict[str, dict[str, float]] = {
    "dg": {
        "concentration_top5_pct": 50,
        "materialisation_pct": 80,
        "contentieux_jours": 90,
        "rupture_silence_jours": 180,
        "echeance_fenetre_jours": 60,
        "visibilite_mois_min": 3,
        "book_to_bill_min": 1.0,
    },
    "dir_commercial": {
        "dormance_jours": 15,
        "echeance_fenetre_jours": 60,
        "concentration_top5_pct": 50,
    },
    "dir_financier": {
        "retard_relance_jours": 30,
        "contentieux_jours": 90,
        "materialisation_pct": 80,
    },
    "dir_operations": {
        "materialisation_pct": 80,
        "visibilite_mois_min": 3,
    },
    "commercial": {
        "dormance_jours": 15,
        "echeance_fenetre_jours": 30,
        "rupture_silence_jours": 180,
    },
}

# Même compromis de cache que `preferences` : invalidation immédiate dans le
# process qui écrit, TTL court pour les autres workers. La lecture est rare (une
# par génération de briefing).
_cache: dict[str, dict[str, float]] | None = None
_cache_at: float = 0.0
_CACHE_TTL = 30.0


def invalidate_cache() -> None:
    global _cache
    _cache = None


def defauts_pour(role: str) -> dict[str, float]:
    """Défauts du rôle, complétés par ceux du catalogue pour les clés non citées."""
    valeurs = {cle: s.defaut for cle, s in CATALOGUE.items()}
    valeurs.update(DEFAUTS.get(role, {}))
    return valeurs


def _borner(cle: str, valeur: float) -> float | None:
    """Une valeur hors bornes est REFUSÉE, jamais rabotée en silence.

    Rogner ferait accepter un enregistrement sans dire que la valeur retenue
    n'est pas celle demandée — le réglage paraîtrait pris en compte et ne le
    serait pas.
    """
    seuil = CATALOGUE.get(cle)
    if seuil is None:
        return None
    try:
        valeur = float(valeur)
    except (TypeError, ValueError):
        return None
    if valeur != valeur or valeur < seuil.mini or valeur > seuil.maxi:  # NaN inclus
        return None
    return valeur


async def _lire() -> list[BriefingSeuilModel]:
    async with AsyncSessionLocal() as session:
        return list((await session.execute(select(BriefingSeuilModel))).scalars())


async def charger_tous() -> dict[str, dict[str, float]]:
    """Seuils des cinq rôles, en une requête — `service.generate` calcule les
    cinq sections en parallèle."""
    global _cache, _cache_at
    if _cache is not None and time.monotonic() - _cache_at < _CACHE_TTL:
        return _cache

    valeurs = {role: defauts_pour(role) for role in DEFAUTS}
    try:
        lignes = await _lire()
    except Exception as exc:
        # Les défauts du code reproduisent EXACTEMENT le comportement d'avant
        # cette fonctionnalité : une table illisible doit donc coûter les
        # réglages, jamais le briefing. Sans ce filet, l'ajout d'une seconde
        # lecture de base dans `service.generate` — après celle des préférences
        # — doublait la surface d'échec d'une génération complète, pour un
        # gain qui n'est qu'un confort de réglage.
        logger.warning("Seuils du débrief illisibles, défauts appliqués : %s", exc)
        return valeurs
    for row in lignes:
        if row.role not in valeurs or row.cle not in CATALOGUE:
            # Rôle ou clé retirés du code : la ligne survit en base, elle est
            # ignorée à la lecture. Jamais une exception — un seuil orphelin
            # ne doit pas coûter le briefing.
            continue
        borne = _borner(row.cle, row.valeur)
        if borne is None:
            logger.warning(
                "Seuil '%s' du rôle '%s' hors bornes (%r) — défaut appliqué",
                row.cle, row.role, row.valeur,
            )
            continue
        valeurs[row.role][row.cle] = borne

    _cache, _cache_at = valeurs, time.monotonic()
    return valeurs


async def charger(role: str) -> dict[str, float]:
    return (await charger_tous()).get(role, defauts_pour(role))


async def enregistrer(role: str, valeurs: dict[str, float], updated_by: str) -> dict:
    """Écrit les seuils d'un rôle. Rend les valeurs retenues et celles refusées.

    Les refus sont RENDUS et non journalisés seulement : l'écran de réglages doit
    pouvoir dire « 400 % de concentration n'est pas une valeur », sinon
    l'utilisateur croit avoir réglé quelque chose.
    """
    if role not in DEFAUTS:
        raise ValueError(f"Rôle inconnu : {role}")

    retenues: dict[str, float] = {}
    refusees: dict[str, str] = {}
    for cle, brut in (valeurs or {}).items():
        if cle not in CATALOGUE:
            refusees[cle] = "seuil inconnu"
            continue
        borne = _borner(cle, brut)
        if borne is None:
            s = CATALOGUE[cle]
            refusees[cle] = f"valeur attendue entre {s.mini:g} et {s.maxi:g}"
        else:
            retenues[cle] = borne

    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        for cle, valeur in retenues.items():
            row = await session.get(BriefingSeuilModel, {"role": role, "cle": cle})
            if row is None:
                row = BriefingSeuilModel(role=role, cle=cle)
                session.add(row)
            row.valeur = valeur
            row.updated_by = updated_by or ""
            row.updated_at = maintenant
        await session.commit()

    invalidate_cache()
    return {"retenues": retenues, "refusees": refusees,
            "seuils": await charger(role), "updated_at": maintenant.isoformat()}


async def reinitialiser(role: str) -> dict[str, float]:
    """Supprime les lignes du rôle : les défauts du code redeviennent la règle."""
    if role not in DEFAUTS:
        raise ValueError(f"Rôle inconnu : {role}")
    async with AsyncSessionLocal() as session:
        for row in (await session.execute(
            select(BriefingSeuilModel).where(BriefingSeuilModel.role == role)
        )).scalars().all():
            await session.delete(row)
        await session.commit()
    invalidate_cache()
    return defauts_pour(role)


async def catalogue_pour(role: str) -> list[dict]:
    """Catalogue ET valeurs courantes du rôle, dans une seule réponse.

    Même doctrine que `preferences.catalogue_pour` : les libellés voyagent avec
    les valeurs, le frontend n'en détient pas de copie qui divergerait.
    """
    courants = await charger(role)
    defauts = defauts_pour(role)
    return [
        {
            "cle": s.cle, "libelle": s.libelle, "unite": s.unite, "effet": s.effet,
            "mini": s.mini, "maxi": s.maxi,
            "valeur": courants.get(s.cle, s.defaut),
            "defaut": defauts.get(s.cle, s.defaut),
            "modifie": courants.get(s.cle, s.defaut) != defauts.get(s.cle, s.defaut),
        }
        for s in CATALOGUE.values()
    ]
