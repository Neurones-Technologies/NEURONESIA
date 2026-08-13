"""Objectifs et Gap — §3 et §4 du compte-rendu DC, point le plus bloquant du dossier.

« Suivi de l'écart entre le vendu et l'objectif (indicateur de type Gap). »

Aucun objectif n'existe dans le système et aucun fait du miroir ne permet d'en
inférer un : un objectif est une DÉCISION, pas une donnée synchronisée. Ce module
est donc construit pour fonctionner dans les deux régimes, sans changer de forme :

- objectifs SAISIS (table `commercial_objectives` alimentée) → `source: "reel"` ;
- table vide → gabarit dérivé d'une RÈGLE lisible (CA N-1 + 10 %, cf.
  `statique.REGLE_OBJECTIF_DEMO`) → `source: "mixte"`, car le réalisé auquel il
  est comparé est bien mesuré, lui.

Le mot « mixte » est important : sur cet écran, une moitié de chaque ligne est
mesurée et l'autre est posée. Les présenter sans le dire produirait exactement ce
que le cadrage reproche déjà au briefing quotidien — commenter « la couverture de
l'équipe par rapport aux objectifs » alors qu'aucun objectif n'est fourni.

Trois précautions portées jusqu'à l'écran :

1. LE CA NON NOMINATIF NE DISPARAÎT PAS. « Assistance Commerciale » porte 6 323 M
   FCFA de CA 2025, près de la moitié de l'exercice. Il est écarté du classement
   individuel (ce n'est pas une personne) mais compté dans le total équipe, et sa
   part est affichée. Sans quoi la somme des lignes individuelles ne ferait jamais
   le total et le tableau paraîtrait faux.
2. LA PÉRIODE EN COURS EST INCOMPLÈTE. Comparer un mois entamé à un objectif plein
   fabrique un retard qui n'existe pas : `part_ecoulee_pct` accompagne toujours la
   période courante.
3. L'OBJECTIF N'EST PAS LINÉAIRE. Le gabarit répartit l'année selon une
   saisonnalité (20/25/22/33) plutôt qu'en quatre quarts égaux — un T1
   structurellement creux ne doit pas se lire comme un décrochage.
"""
from __future__ import annotations

from datetime import date

from modules.uc_commercial import statique
from modules.uc_commercial.referentiel import normaliser

PERIODES = ("mois", "trimestre", "annee")

LIBELLES_MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _index_periode(periode: str, mois: int) -> int:
    if periode == "mois":
        return mois
    if periode == "trimestre":
        return (mois - 1) // 3 + 1
    return 0


def _libelle_periode(periode: str, index: int, annee: int) -> str:
    if periode == "mois":
        return f"{LIBELLES_MOIS[index - 1].capitalize()} {annee}"
    if periode == "trimestre":
        return f"T{index} {annee}"
    return str(annee)


def _nb_periodes(periode: str) -> int:
    return {"mois": 12, "trimestre": 4, "annee": 1}[periode]


def _part_objectif(periode: str, index: int) -> float:
    """Fraction de l'objectif annuel affectée à la période, selon la saisonnalité."""
    if periode == "annee":
        return 1.0
    if periode == "trimestre":
        return statique.SAISONNALITE_TRIMESTRES.get(index, 0.25)
    trimestre = (index - 1) // 3 + 1
    return statique.SAISONNALITE_TRIMESTRES.get(trimestre, 0.25) / 3


def _part_ecoulee(periode: str, index: int, annee: int, today: date) -> float | None:
    """Fraction écoulée de la période, ou `None` si elle est révolue ou à venir."""
    if annee != today.year:
        return None
    if periode == "annee":
        debut = date(annee, 1, 1)
        return round(100 * ((today - debut).days + 1) / 365, 1)
    if periode == "trimestre":
        if index != (today.month - 1) // 3 + 1:
            return None
        mois_ecoules = (today.month - 1) % 3
        return round(100 * (mois_ecoules * 30 + today.day) / 91, 1)
    if index != today.month:
        return None
    return round(100 * today.day / 30, 1)


def _statut_periode(periode: str, index: int, annee: int, today: date) -> str:
    """"revolue" | "en_cours" | "a_venir" — décide si un taux d'atteinte a un sens."""
    if annee < today.year:
        return "revolue"
    if annee > today.year:
        return "a_venir"
    if periode == "annee":
        return "en_cours"
    courant = today.month if periode == "mois" else (today.month - 1) // 3 + 1
    if index < courant:
        return "revolue"
    return "en_cours" if index == courant else "a_venir"


def _agrege_par_commercial(lignes: list[dict], index_resolution: dict) -> tuple[dict, dict]:
    """CA par identité canonique, en séparant personnes et porteurs non nominatifs."""
    from modules.uc_commercial.referentiel import resoudre

    personnes: dict[str, dict] = {}
    autres: dict[str, dict] = {}
    for l in lignes:
        resolu = resoudre(index_resolution, l["commercial"])
        cible = autres if resolu["nature"] in ("technique", "collectif") else personnes
        entree = cible.setdefault(resolu["salesperson_id"] or normaliser(l["commercial"]), {
            "salesperson_id": resolu["salesperson_id"],
            "display_name": resolu["display_name"],
            "nature": resolu["nature"],
            "ca_xof": 0,
            "nb_commandes": 0,
            "par_mois": {},
        })
        entree["ca_xof"] += l["ca_xof"]
        entree["nb_commandes"] += l["nb"]
        m = entree["par_mois"].setdefault(l["mois"], {"ca_xof": 0, "nb": 0})
        m["ca_xof"] += l["ca_xof"]
        m["nb"] += l["nb"]
    return personnes, autres


def _objectifs_demo(personnes: dict, total_n1: float) -> tuple[float, dict[str, float]]:
    """Objectif annuel équipe et répartition individuelle, selon la règle de démonstration."""
    objectif_equipe = round(total_n1 * statique.COEFF_OBJECTIF_DEMO)
    base = sum(p["ca_xof"] for p in personnes.values())
    if base <= 0:
        return objectif_equipe, {}
    # Le prorata s'applique à la part NOMINATIVE de l'objectif, pas à l'objectif
    # entier : répartir tout l'objectif entre les seules personnes leur imputerait
    # le CA porté par les entités collectives.
    part_nominative = base / total_n1 if total_n1 else 0
    enveloppe = objectif_equipe * part_nominative
    return objectif_equipe, {
        cle: round(enveloppe * p["ca_xof"] / base) for cle, p in personnes.items()
    }


def build_objectifs_gap(
    objectifs_bdd: list[dict],
    ca_annee: list[dict],
    ca_annee_precedente: list[dict],
    index_resolution: dict,
    annee: int,
    periode: str = "trimestre",
    today: date | None = None,
) -> dict:
    """Gap vendu / objectif, décliné sur la cadence demandée (mois, trimestre, année)."""
    jour = today or date.today()
    if periode not in PERIODES:
        periode = "trimestre"

    personnes, autres = _agrege_par_commercial(ca_annee, index_resolution)
    personnes_n1, autres_n1 = _agrege_par_commercial(ca_annee_precedente, index_resolution)

    realise_total = sum(p["ca_xof"] for p in personnes.values()) + sum(a["ca_xof"] for a in autres.values())
    realise_nominatif = sum(p["ca_xof"] for p in personnes.values())
    total_n1 = sum(p["ca_xof"] for p in personnes_n1.values()) + sum(a["ca_xof"] for a in autres_n1.values())

    # ── Objectifs : saisis s'ils existent, gabarit sinon ─────────────────────
    saisis_equipe = [
        o for o in objectifs_bdd
        if o["scope"] == "equipe" and o["kind"] == "ca" and o["period_year"] == annee and o["period_type"] == "annee"
    ]
    saisis_individuels = {
        o["scope_ref"]: o["target_amount_xof"]
        for o in objectifs_bdd
        if o["scope"] == "commercial" and o["kind"] == "ca" and o["period_year"] == annee and o["period_type"] == "annee"
    }

    if saisis_equipe:
        objectif_annuel = sum(o["target_amount_xof"] for o in saisis_equipe)
        objectifs_individuels = dict(saisis_individuels)
        source = statique.SOURCE_REELLE
        origine = "objectifs saisis dans le référentiel de pilotage"
        regle = None
    else:
        objectif_annuel, objectifs_individuels = _objectifs_demo(personnes_n1 or personnes, total_n1 or realise_total)
        source = statique.SOURCE_MIXTE
        origine = "gabarit : aucun objectif n'est saisi dans le référentiel de pilotage"
        regle = statique.REGLE_OBJECTIF_DEMO

    # ── Cadence : une ligne par période de l'année ───────────────────────────
    realise_par_index: dict[int, dict] = {}
    for l in ca_annee:
        idx = _index_periode(periode, l["mois"])
        e = realise_par_index.setdefault(idx, {"ca_xof": 0, "nb": 0})
        e["ca_xof"] += l["ca_xof"]
        e["nb"] += l["nb"]

    periodes: list[dict] = []
    for i in range(1, _nb_periodes(periode) + 1):
        idx = 0 if periode == "annee" else i
        obj = round(objectif_annuel * _part_objectif(periode, idx))
        rea = realise_par_index.get(idx, {"ca_xof": 0, "nb": 0})
        ecoulee = _part_ecoulee(periode, idx, annee, jour)
        statut = _statut_periode(periode, idx, annee, jour)
        periodes.append({
            "index": idx,
            "libelle": _libelle_periode(periode, idx if idx else annee, annee),
            "objectif_xof": obj,
            "realise_xof": rea["ca_xof"],
            "nb_commandes": rea["nb"],
            "ecart_xof": rea["ca_xof"] - obj,
            # Un taux d'atteinte n'est publié que sur une période commencée : un
            # trimestre à venir afficherait « 0 % » et se lirait comme un échec.
            "taux_pct": round(100 * rea["ca_xof"] / obj, 1) if obj and statut != "a_venir" else None,
            "statut": statut,
            "en_cours": statut == "en_cours",
            "part_ecoulee_pct": ecoulee,
        })

    # ── Gap par commercial ───────────────────────────────────────────────────
    lignes_commerciaux: list[dict] = []
    for cle, p in personnes.items():
        obj = objectifs_individuels.get(p["salesperson_id"] or cle, 0)
        lignes_commerciaux.append({
            "salesperson_id": p["salesperson_id"],
            "display_name": p["display_name"],
            "objectif_xof": round(obj),
            # Un commercial qui vend cette année sans avoir vendu l'an dernier
            # (arrivée, changement de portefeuille) n'a pas d'objectif calculable
            # par la règle du gabarit. Le dire est plus utile que lui affecter un
            # chiffre : c'est précisément le cas qui impose la saisie manuelle.
            "objectif_absent": obj <= 0,
            "motif_objectif_absent": (
                "aucun réalisé sur l'année précédente : le gabarit ne peut pas lui attribuer d'objectif, "
                "il doit être saisi"
            ) if obj <= 0 else None,
            "realise_xof": p["ca_xof"],
            "ecart_xof": round(p["ca_xof"] - obj),
            "taux_pct": round(100 * p["ca_xof"] / obj, 1) if obj else None,
            "nb_commandes": p["nb_commandes"],
            "part_ca_equipe_pct": round(100 * p["ca_xof"] / realise_total, 1) if realise_total else 0.0,
        })
    lignes_commerciaux.sort(key=lambda l: -l["realise_xof"])

    non_nominatifs = sorted(
        (
            {
                "display_name": a["display_name"],
                "nature": a["nature"],
                "realise_xof": a["ca_xof"],
                "nb_commandes": a["nb_commandes"],
                "part_ca_equipe_pct": round(100 * a["ca_xof"] / realise_total, 1) if realise_total else 0.0,
            }
            for a in autres.values()
        ),
        key=lambda a: -a["realise_xof"],
    )

    return {
        "source": source,
        "origine_objectifs": origine,
        "regle_gabarit": regle,
        "avertissement": statique.AVERTISSEMENT_STATIQUE if regle else None,
        "annee": annee,
        "periode": periode,
        "as_of": jour.isoformat(),
        "equipe": {
            "objectif_annuel_xof": objectif_annuel,
            "realise_xof": realise_total,
            "ecart_xof": round(realise_total - objectif_annuel),
            "taux_pct": round(100 * realise_total / objectif_annuel, 1) if objectif_annuel else None,
            "realise_annee_precedente_xof": round(total_n1),
            "part_ecoulee_annee_pct": _part_ecoulee("annee", 0, annee, jour),
        },
        "periodes": periodes,
        "commerciaux": lignes_commerciaux,
        "porteurs_non_nominatifs": non_nominatifs,
        "couverture": {
            "realise_nominatif_xof": realise_nominatif,
            "part_nominative_pct": round(100 * realise_nominatif / realise_total, 1) if realise_total else 0.0,
            "nb_commerciaux": len(lignes_commerciaux),
            "nb_porteurs_non_nominatifs": len(non_nominatifs),
            "somme_objectifs_individuels_xof": round(sum(l["objectif_xof"] for l in lignes_commerciaux)),
        },
        "note": (
            "Le réalisé est MESURÉ sur les commandes signées ; l'objectif, lui, vient du référentiel de "
            "pilotage — et tant qu'il n'y est pas saisi, d'un gabarit calculé sur l'année précédente. "
            "La somme des objectifs individuels est inférieure à l'objectif d'équipe : la différence "
            "correspond au CA porté par des entités non nominatives, réel mais imputable à personne. "
            "Une période en cours est comparée à un objectif plein : la part écoulée est affichée pour "
            "que l'écart se lise à date comparable."
        ),
    }
