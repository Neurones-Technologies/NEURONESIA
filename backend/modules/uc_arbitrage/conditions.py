"""Conditions d'entrée en arbitrage — catalogue figé dans le code, activable par profil.

Le socle de la file (« un impayé échu ET un signal commercial actif sur le même
client », cf. `aggregation.detect_client_conflicts`) définit ce QU'EST un dossier
d'arbitrage : il n'est pas décochable, sans quoi le module cesse d'être un module
d'arbitrage pour devenir une liste d'impayés. Ce fichier porte ce qui vient
par-dessus : quatre conditions restrictives que chaque profil active ou non, et
qui se combinent en ET.

Pourquoi le catalogue est dans le code et non en base :
  - une condition d'entrée décide de ce qui est SOUMIS À DÉCISION ; elle doit
    rester relisible et testée, pas rédigée à l'écran ;
  - une règle saisie en texte libre exigerait d'être interprétée à chaque calcul,
    donc un résultat non reproductible sur un écran dont toute la valeur tient à
    ce qu'il peut dire POURQUOI un dossier est là.
Seule l'ACTIVATION est persistée (cf. `db/models.py::ArbitrageParamModel`).

Trois invariants tiennent l'ensemble :

1. Toutes les conditions sont RESTRICTIVES, formulées « ne remonter que si… ».
   Comme elles se combinent en ET, une condition inclusive (« faire remonter
   aussi… ») ne pourrait rien ajouter : cochée avec une autre, elle ne saurait
   qu'enlever. Toute condition ajoutée ici doit respecter cette forme.

2. Aucune condition ne lit un champ pouvant être inconnu. `impaye_xof`,
   `enjeu_xof`, `retard_max_jours`, `signal_type` et `profil_payeur.classe` sont
   toujours renseignés par construction (`payeur.build_payeur_profile` produit
   une classe même sans historique, précisément pour ne pas laisser de trou).
   C'est ce qui évite une logique à trois valeurs et la question insoluble qui
   l'accompagne : un dossier dont l'information manque doit-il sortir de la file ?

3. Zéro condition active = socle seul = comportement d'avant ce réglage. Les
   défauts livrés sont donc vides ; les réglages recommandés (`recommandee_pour`)
   ne sont qu'un conseil affiché, jamais appliqué d'office. Personne ne doit voir
   son écran changer parce que la fonctionnalité a été déployée.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ── Seuils, en dur et commentés ───────────────────────────────────────────────

# Au-delà de deux ans de retard, le sujet n'est plus un arbitrage entre
# recouvrement et vente : c'est du contentieux ou une créance à provisionner.
# Mesuré sur le miroir : 53 % des factures ouvertes échues (457 sur 865, pour
# ~3,8 Md FCFA) dépassent ce seuil et encombrent la file de dossiers sur
# lesquels aucune décision commerciale n'a plus de prise.
RETARD_PLAFOND_JOURS = 730

# Classes de payeur qui traduisent un CHANGEMENT de comportement (cf.
# payeur.CLASSE_LABELS). Un payeur public lent depuis toujours n'y figure pas :
# son retard est son rythme, pas un signal.
CLASSES_EN_MOUVEMENT = (
    "degradation",
    "vigilance",
    "paiements_stoppes",
    "defaillance_probable",
)

# Seul type de signal sur lequel l'entreprise détient un vrai levier : une
# reconduction se conditionne. Une obsolescence ne se conditionne pas — le client
# peut simplement ne pas racheter, et « conditionner » revient à perdre l'affaire.
SIGNAL_LEVIER = "Renouvellement"

# Profils pouvant porter un réglage. Miroir des rôles ouverts sur la vue
# « arbitrage » (cf. config/permissions.py::DEFAULT_MODULE_ACCESS) — volontairement
# recopié plutôt qu'importé : un rôle qui perdrait l'accès à la vue laisserait ici
# une entrée inutilisée, pas une erreur.
PROFILS_PARAMETRABLES = ("dg", "dir_financier", "dir_commercial", "dir_operations", "commercial")


@dataclass(frozen=True)
class Condition:
    """Une case à cocher. `predicat` reçoit un dossier tel que produit par
    `aggregation.detect_client_conflicts` et répond « ce dossier reste »."""

    code: str
    libelle: str
    explication: str
    seuil: str
    champs: tuple[str, ...]
    # Profils pour lesquels cette condition est conseillée — affiché comme un
    # repère, jamais appliqué automatiquement (cf. invariant 3).
    recommandee_pour: tuple[str, ...]
    predicat: Callable[[dict], bool]


def _nombre(valeur) -> float:
    try:
        return float(valeur or 0)
    except (TypeError, ValueError):
        return 0.0


def _classe(dossier: dict) -> str:
    return str((dossier.get("profil_payeur") or {}).get("classe") or "")


CATALOGUE: tuple[Condition, ...] = (
    Condition(
        code="impaye_superieur_enjeu",
        libelle="L'impayé dépasse l'enjeu commercial",
        explication=(
            "La seule condition sans seuil : elle se recalibre sur chaque dossier. Elle sépare "
            "les clients qui doivent plus qu'ils ne vont rapporter — où l'on négocie en position "
            "de force — de ceux dont l'affaire en cours vaut plus que l'ardoise, où bloquer coûte "
            "plus cher qu'attendre."
        ),
        seuil="",
        champs=("impaye_xof", "enjeu_xof"),
        recommandee_pour=("dg", "dir_financier"),
        predicat=lambda d: _nombre(d.get("impaye_xof")) >= _nombre(d.get("enjeu_xof")),
    ),
    Condition(
        code="retard_plafond",
        libelle="Écarter les créances de plus de 2 ans",
        explication=(
            "Au-delà de deux ans, le dossier relève du contentieux ou de la provision, plus de "
            "l'arbitrage entre recouvrement et vente. Plus de la moitié des factures échues du "
            "miroir sont dans ce cas : sans cette condition, elles occupent la file sans qu'aucune "
            "décision commerciale n'ait de prise sur elles."
        ),
        seuil=f"{RETARD_PLAFOND_JOURS} jours",
        champs=("retard_max_jours",),
        recommandee_pour=("dir_financier",),
        predicat=lambda d: _nombre(d.get("retard_max_jours")) <= RETARD_PLAFOND_JOURS,
    ),
    Condition(
        code="classe_en_mouvement",
        libelle="Le comportement de paiement s'est cassé",
        explication=(
            "Ne garde que les clients dont le rythme de paiement a changé (dégradation, vigilance, "
            "paiements stoppés, défaillance probable). Un payeur public lent depuis toujours mais "
            "régulier en sort : son retard est son rythme habituel, pas un signal — et c'est "
            "exactement la confusion que le profil de payeur sert à lever."
        ),
        seuil="",
        champs=("profil_payeur.classe",),
        recommandee_pour=("dg",),
        predicat=lambda d: _classe(d) in CLASSES_EN_MOUVEMENT,
    ),
    Condition(
        code="signal_renouvellement",
        libelle="Renouvellements uniquement",
        explication=(
            "Ne garde que les dossiers où l'entreprise a un levier réel : une reconduction se "
            "conditionne au paiement. Une obsolescence ou un cross-sell, non — le client peut "
            "simplement ne pas acheter, et l'on aura perdu l'affaire sans rien récupérer."
        ),
        seuil="",
        champs=("signal_type",),
        recommandee_pour=("dir_commercial", "commercial"),
        predicat=lambda d: str(d.get("signal_type") or "") == SIGNAL_LEVIER,
    ),
)

_PAR_CODE = {c.code: c for c in CATALOGUE}


def codes_connus() -> tuple[str, ...]:
    return tuple(_PAR_CODE)


def normaliser(codes) -> list[str]:
    """Ne garde que les codes réellement implémentés, dans l'ordre du catalogue.

    C'est ici que se joue la règle « on applique la combinaison si elle existe
    dans le backend » : un code inconnu — condition retirée du catalogue mais
    restée en base, ou charge utile fantaisiste — est ignoré, jamais une erreur.
    Une file d'arbitrage ne doit pas tomber parce qu'un réglage a vieilli.
    """
    if not isinstance(codes, (list, tuple, set)):
        return []
    demandes = {str(c) for c in codes}
    return [c.code for c in CATALOGUE if c.code in demandes]


def inconnus(codes) -> list[str]:
    """Codes reçus mais non implémentés — pour les journaliser côté appelant."""
    if not isinstance(codes, (list, tuple, set)):
        return []
    return sorted({str(c) for c in codes} - set(_PAR_CODE))


def appliquer(dossiers: list[dict], codes) -> list[dict]:
    """File restreinte aux dossiers qui satisfont TOUTES les conditions actives.

    Le ET est la sémantique retenue : chaque case cochée resserre la file. Aucune
    case cochée ne restreint donc rien, et le résultat est la file du socle.
    """
    actives = [_PAR_CODE[c] for c in normaliser(codes)]
    if not actives:
        return list(dossiers)
    return [d for d in dossiers if all(c.predicat(d) for c in actives)]


def mesurer(dossiers: list[dict], actives) -> dict:
    """Effet de chaque condition sur la file réelle, plus celui de la combinaison
    active. C'est ce qui permet à l'écran d'afficher « 2 dossiers sur 7 » AVANT
    que l'utilisateur ne coche, au lieu de le laisser vider sa file sans
    comprendre pourquoi — le principal risque du ET.
    """
    total = len(dossiers)
    retenus = len(appliquer(dossiers, actives))
    return {
        "nb_total": total,
        "nb_retenus": retenus,
        "nb_ecartes": total - retenus,
        # Références retenues par chaque condition PRISE SEULE. L'écran en déduit
        # l'effet de n'importe quelle combinaison par simple intersection, sans
        # aller-retour serveur : le compteur reste vivant pendant que
        # l'utilisateur coche, et c'est indispensable — le ET n'est pas intuitif,
        # deux conditions raisonnables peuvent vider la file.
        "refs_par_condition": {
            c.code: [str(d.get("subject_ref") or "") for d in dossiers if c.predicat(d)]
            for c in CATALOGUE
        },
        "refs_total": [str(d.get("subject_ref") or "") for d in dossiers],
    }


def catalogue_public() -> list[dict]:
    """Catalogue sérialisable — ce que l'écran de réglages affiche."""
    return [
        {
            "code": c.code,
            "libelle": c.libelle,
            "explication": c.explication,
            "seuil": c.seuil,
            "champs": list(c.champs),
            "recommandee_pour": list(c.recommandee_pour),
        }
        for c in CATALOGUE
    ]
