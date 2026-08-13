"""Outils de datation et de ratio partagés par les trois tableaux de bord DAF.

Ces fonctions sont ici et non recopiées dans chaque module pour une raison précise :
les trois écrans financiers comparent tous un réalisé à une période, et une
divergence d'un jour entre deux définitions de « part de l'exercice écoulée »
produirait deux verdicts différents sur le même exercice.

Aucune fonction ne lit `date.today()` : la date d'observation est toujours passée
en argument. C'est ce qui rend les calculs testables — le statut d'un mois, la
vigilance d'une échéance et la part écoulée dépendent tous du jour où on regarde.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

LIBELLES_MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

LIBELLES_MOIS_COURTS = [
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
]


def jour(iso: str | None) -> date | None:
    """Date d'une chaîne `YYYY-MM-DD`, `None` si absente ou illisible.

    Tolérante par choix : une date mal formée dans le miroir ne doit pas faire
    tomber un tableau de bord entier. La ligne concernée sera comptée comme non
    datée, ce que les contrôles de qualité remontent déjà.
    """
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def cle_mois(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def libelle_mois(annee: int, mois: int, court: bool = False) -> str:
    libelles = LIBELLES_MOIS_COURTS if court else LIBELLES_MOIS
    return f"{libelles[mois - 1]} {annee}"


def mois_suivant(annee: int, mois: int) -> tuple[int, int]:
    return (annee + 1, 1) if mois == 12 else (annee, mois + 1)


def fin_de_mois(annee: int, mois: int) -> date:
    return date(annee, mois, monthrange(annee, mois)[1])


def part_ecoulee_exercice_pct(annee: int, aujourdhui: date) -> float | None:
    """Part de l'exercice écoulée, en pourcentage — `None` sur un exercice révolu.

    Sert de correcteur de lecture partout : comparer un réalisé à date à un budget
    ou un objectif annuel plein fabrique un écart qui n'existe pas.
    """
    if aujourdhui.year > annee:
        return None
    if aujourdhui.year < annee:
        return 0.0
    debut = date(annee, 1, 1)
    total = (date(annee, 12, 31) - debut).days + 1
    return round(((aujourdhui - debut).days + 1) / total * 100, 1)


def pct(numerateur: float, denominateur: float) -> float:
    """Pourcentage, 0 si le dénominateur est nul — jamais une division qui casse."""
    if not denominateur:
        return 0.0
    return round(numerateur / denominateur * 100, 1)


def taux_atteinte_pct(mesure: float | None, cible: float, sens: str = "haut") -> float | None:
    """Taux d'atteinte d'une cible, borné à 120 %.

    `sens="haut"` : plus la mesure est grande, mieux c'est (marge, recouvrement).
    `sens="bas"`  : plus la mesure est petite, mieux c'est (DSO, délai).

    Le plafond de 120 % est un choix de lecture : sans lui, une composante
    exceptionnelle compenserait à elle seule l'effondrement de deux autres dans
    l'indice composite, ce qui est exactement ce qu'un indicateur global ne doit
    pas faire.
    """
    if mesure is None or not cible:
        return None
    brut = (cible / mesure * 100) if sens == "bas" and mesure else (mesure / cible * 100)
    return round(max(0.0, min(120.0, brut)), 1)
