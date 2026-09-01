"""Écriture des montants en FCFA — règle unique, partagée par tout le backend.

Le jumeau côté navigateur est `frontend/src/lib/format.ts` (`formatFcfa`). Les
deux DOIVENT rendre la même chaîne pour le même montant : les puces du briefing
et les tuiles du cockpit affichent souvent le même indicateur, et deux écritures
différentes du même nombre se lisent comme deux chiffres différents.

La règle : l'échelle est portée par le montant LUI-MÊME, jamais par l'écran.

    850 000        → « 850 000 »   (sous le million : chiffres entiers)
    6 128 000      → « 6,13 M »
    111 000 000    → « 111 M »
    6 128 000 000  → « 6,13 Md »

Deux montants voisins peuvent donc s'écrire l'un en M et l'autre en Md, et c'est
voulu : une échelle imposée à tout un écran écrase soit les petits montants à
« 0 M », soit les gros en une file de zéros illisible.

L'unité monétaire n'est PAS incluse — l'appelant ajoute « FCFA ». Le suffixe
d'échelle, lui, est collé au nombre : c'est ce qui empêche un montant d'être
recopié sans son ordre de grandeur et de devenir faux d'un facteur mille.
"""
from __future__ import annotations

# Espace insécable étroit : le séparateur de milliers français. Un espace
# ordinaire laisserait « 850 000 » se couper en fin de ligne, et le lecteur
# verrait « 850 » seul.
_ESPACE = " "


def _decimales(valeur: float) -> int:
    """Décimales choisies pour garder ~3 chiffres significatifs à l'échelle
    retenue. « 6,13 Md » et « 111 M » se lisent d'un coup d'œil ; « 6,128571 Md »
    noie le lecteur et « 111,0 M » affiche une précision qu'on n'a pas."""
    absolu = abs(valeur)
    if absolu < 10:
        return 2
    if absolu < 100:
        return 1
    return 0


def _fr(valeur: float, decimales: int) -> str:
    """Nombre à la française : virgule décimale, espace pour les milliers."""
    brut = f"{valeur:,.{decimales}f}"           # 6,128.57  (convention anglaise)
    return brut.replace(",", _ESPACE).replace(".", ",")


def fcfa(xof: float | int | None) -> str:
    """Montant à l'échelle qui lui convient (cf. l'en-tête du module)."""
    valeur = float(xof or 0)
    absolu = abs(valeur)

    # Sous le million, aucune abréviation : « 0,85 M » se lit moins bien que
    # « 850 000 », et arrondir un petit montant à l'échelle du million le noie.
    if absolu < 1_000_000:
        return _fr(valeur, 0)

    # L'ARRONDI peut promouvoir l'échelle, et c'est le nombre AFFICHÉ qu'il faut
    # tester, pas le nombre brut : 999 999 999 vaut 999,999999 M, que zéro
    # décimale rend « 1 000 M » — une unité qu'on lit de travers alors que
    # « 1,00 Md » est le même montant, correctement nommé. Un simple seuil
    # `absolu >= 1e9` laisserait passer tout l'intervalle 999,5 M – 999,999 M.
    en_m = valeur / 1_000_000
    if abs(round(en_m, _decimales(en_m))) < 1_000:
        return f"{_fr(en_m, _decimales(en_m))}{_ESPACE}M"
    en_md = valeur / 1_000_000_000
    return f"{_fr(en_md, _decimales(en_md))}{_ESPACE}Md"


def fcfa_signe(xof: float | int | None) -> str:
    """`fcfa` avec signe explicite — pour les écarts, où « +2 M » et « 2 M » ne
    disent pas la même chose. Le signe précède le nombre ET son échelle."""
    valeur = float(xof or 0)
    return f"+{fcfa(valeur)}" if valeur >= 0 else fcfa(valeur)


def fcfa_depuis_m(millions: float | int | None) -> str:
    """`fcfa` pour une valeur DÉJÀ EXPRIMÉE EN MILLIONS (champs `*_m_fcfa`,
    seuil de mandat DG, coût de report). Ces valeurs ne doivent jamais passer
    par `fcfa`, qui les rendrait mille fois trop petites — l'erreur est
    silencieuse et parfaitement crédible à l'écran."""
    return fcfa(float(millions or 0) * 1_000_000)
