"""Segmentation du portefeuille par rythme de commande — suivi dormant/actif du DC.

Répond à la section 3 du cadrage DC (« Comptes dormants et actifs »), qui notait
qu'un moteur existait avec des seuils « jamais validés métier ». Les seuils ci-dessous
SONT validés : 6 mois pour le décrochage, la mesure porte sur les commandes signées,
et le livrable est un suivi d'état — pas une liste d'actions.

Fonction pure sur des dicts, `today` injecté, comme `build_montee_valeur`
(modules/uc_crosssell) et `build_offer_mix` (modules/uc_offermix).

Trois précautions de lecture que le résultat doit porter jusqu'à l'écran :

1. LA SEGMENTATION GLISSE. Elle dépend de la date d'observation : ~10 comptes
   changent de segment chaque mois. D'où `as_of` dans le retour, à afficher — sans
   quoi deux lectures prises à quinze jours d'écart semblent se contredire.

2. « DORMANT » A UN AUTRE SENS AILLEURS. `get_account_rhythm_breaks()` de l'adapter
   mesure une rupture RELATIVE (silence > 2,5 × l'intervalle médian du compte, sur
   les comptes ≥ 3 commandes et ≥ 100 M de CA annuel) et alimente le briefing DG.
   Ici la mesure est ABSOLUE et couvre tout le portefeuille. Les deux nombres de
   « dormants » ne sont pas comparables ; `note` le dit explicitement.

3. LE SILENCE SE MESURE SUR LES COMMANDES SIGNÉES. Un compte qui génère des
   opportunités sans jamais signer est donc compté dormant — contre-intuitif et
   fréquent (45 comptes dormants portent 9 800 M de pipe ouvert). C'est exposé via
   `nb_avec_opp_ouverte`, pas masqué.
"""
from __future__ import annotations

from datetime import date, datetime

# Seuils VALIDÉS par la Direction Commerciale (contrairement à ceux du cross-sell,
# qui sont des valeurs par défaut). Bornes fermées à gauche : un compte à exactement
# 6 mois de silence est « Ralentit », pas « Actif ».
_SEUIL_RALENTIT_MOIS = 6
_SEUIL_DORMANT_MOIS = 12
_SEUIL_PERDU_MOIS = 24

SEGMENT_ORDER: list[str] = ["actif", "ralentit", "dormant", "perdu", "prospect"]

SEGMENT_LABELS: dict[str, str] = {
    "actif": "Actif",
    "ralentit": "Ralentit",
    "dormant": "Dormant",
    "perdu": "Perdu",
    "prospect": "Prospect",
}

SEGMENT_BORNES: dict[str, str] = {
    "actif": "moins de 6 mois",
    "ralentit": "6 à 12 mois",
    "dormant": "12 à 24 mois",
    "perdu": "plus de 24 mois",
    # « jamais commandé » et non « jamais facturé » : les deux notions diffèrent
    # (180 comptes ayant commandé n'ont aucune facture, 5 comptes sans commande en
    # ont). La segmentation portant sur les commandes, le libellé doit suivre.
    "prospect": "jamais commandé",
}

# Segments considérés comme « décrochés » : c'est le cœur du suivi d'état.
_SEGMENTS_DECROCHAGE = ("ralentit", "dormant")
# Segments dont le CA est sorti du radar (historique cumulé, PAS une perte de l'exercice).
_SEGMENTS_SOMMEIL = ("dormant", "perdu")

_NOTE = (
    "Silence mesuré sur les commandes signées (sale_orders), pas sur les opportunités : "
    "un compte peut donc apparaître dormant tout en portant des affaires ouvertes. "
    "Segmentation absolue sur l'ancienneté — distincte de la « rupture de rythme » du "
    "briefing DG, qui compare chaque compte à son propre intervalle médian de commande."
)


def _parse_date(value: str | None) -> date | None:
    """Même tolérance que les autres agrégations : 10 premiers caractères, le miroir
    stockant tantôt une date, tantôt un datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_since(d: date, today: date) -> int:
    """Ancienneté en mois CALENDAIRES — même calcul que `_months_since` du cross-sell.

    Volontairement pas `jours / 30.44` : le résultat dépendrait de la longueur des
    mois traversés, et deux comptes ayant commandé le même mois tomberaient de part
    et d'autre d'un seuil.
    """
    return (today.year - d.year) * 12 + (today.month - d.month)


def _segment(derniere_commande: date | None, today: date) -> tuple[str, int | None]:
    """Segment et silence en mois. `None` de date → prospect, JAMAIS perdu."""
    if derniere_commande is None:
        return "prospect", None
    mois = max(0, _months_since(derniere_commande, today))
    if mois < _SEUIL_RALENTIT_MOIS:
        return "actif", mois
    if mois < _SEUIL_DORMANT_MOIS:
        return "ralentit", mois
    if mois < _SEUIL_PERDU_MOIS:
        return "dormant", mois
    return "perdu", mois


def _pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _median(valeurs: list[int]) -> int | None:
    if not valeurs:
        return None
    ordonnes = sorted(valeurs)
    milieu = len(ordonnes) // 2
    if len(ordonnes) % 2:
        return ordonnes[milieu]
    return (ordonnes[milieu - 1] + ordonnes[milieu]) // 2


def build_suivi_dormance(
    comptes: list[dict],
    today: date | None = None,
    top_n: int = 10,
) -> dict:
    """Segmente le portefeuille par ancienneté de dernière commande.

    `comptes` : sortie de `CRMRepository.get_account_activity()` — clés `compte`,
    `client_id`, `derniere_commande`, `nb_commandes`, `ca_total_xof`, `commercial`,
    `nb_impayes`, `impaye_xof`, `retard_max_jours`, `nb_opp_ouvertes`,
    `opp_ouvertes_xof`, `hors_referentiel`.

    `today` : date d'observation, injectable pour rendre les tests déterministes.
    La segmentation en dépend directement (cf. précaution 1 du module).

    `top_n` : nombre de comptes nominatifs retenus par segment et dans la liste des
    décrochages.
    """
    today = today or date.today()

    enrichis: list[dict] = []
    for c in comptes:
        derniere = _parse_date(c.get("derniere_commande"))
        segment, mois = _segment(derniere, today)
        impaye = c.get("impaye_xof") or 0
        enrichis.append({
            "compte": c.get("compte") or "(compte sans nom)",
            "client_id": c.get("client_id"),
            "segment": segment,
            "mois_silence": mois,
            "derniere_commande": c.get("derniere_commande"),
            "nb_commandes": int(c.get("nb_commandes") or 0),
            "ca_total_xof": round(c.get("ca_total_xof") or 0),
            "commercial": c.get("commercial") or "",
            "nb_impayes": int(c.get("nb_impayes") or 0),
            "impaye_xof": round(impaye),
            "retard_max_jours": int(c.get("retard_max_jours") or 0),
            "nb_opp_ouvertes": int(c.get("nb_opp_ouvertes") or 0),
            "opp_ouvertes_xof": round(c.get("opp_ouvertes_xof") or 0),
            "hors_referentiel": bool(c.get("hors_referentiel")),
            # Un compte silencieux qui doit de l'argent ne se relance pas comme les
            # autres : la décision du DC est de l'afficher et de le signifier.
            "alerte_impaye": impaye > 0,
        })

    nb_total = len(enrichis)
    ca_total = sum(c["ca_total_xof"] for c in enrichis)

    def _fiche(c: dict) -> dict:
        """Vue nominative d'un compte, sans détail de facture.

        Le profil DC n'a pas accès à la vue « tresorerie » (cf. config/permissions.py) :
        on expose donc le DRAPEAU et le MONTANT AGRÉGÉ de l'impayé, jamais la liste
        des factures. Même arbitrage que la vue AM, qui réserve le détail par facture
        aux profils financiers.
        """
        return {
            "compte": c["compte"],
            "client_id": c["client_id"],
            "segment": c["segment"],
            "label": SEGMENT_LABELS[c["segment"]],
            "mois_silence": c["mois_silence"],
            "derniere_commande": c["derniere_commande"],
            "nb_commandes": c["nb_commandes"],
            "ca_total_xof": c["ca_total_xof"],
            "commercial": c["commercial"],
            "alerte_impaye": c["alerte_impaye"],
            "impaye_xof": c["impaye_xof"],
            "retard_max_jours": c["retard_max_jours"],
            "nb_opp_ouvertes": c["nb_opp_ouvertes"],
            "opp_ouvertes_xof": c["opp_ouvertes_xof"],
            "hors_referentiel": c["hors_referentiel"],
        }

    # ── Segments, dans l'ORDRE MÉTIER (jamais trié par volume) ────────────────
    segments = []
    for nom in SEGMENT_ORDER:
        lot = [c for c in enrichis if c["segment"] == nom]
        ca_lot = sum(c["ca_total_xof"] for c in lot)
        avec_impaye = [c for c in lot if c["alerte_impaye"]]
        avec_pipe = [c for c in lot if c["nb_opp_ouvertes"] > 0]
        silences = [c["mois_silence"] for c in lot if c["mois_silence"] is not None]
        segments.append({
            "segment": nom,
            "label": SEGMENT_LABELS[nom],
            "borne": SEGMENT_BORNES[nom],
            "nb_comptes": len(lot),
            "part_nb_pct": _pct(len(lot), nb_total),
            "ca_historique_xof": round(ca_lot),
            "part_ca_pct": _pct(ca_lot, ca_total),
            "nb_avec_impaye": len(avec_impaye),
            "impaye_xof": round(sum(c["impaye_xof"] for c in avec_impaye)),
            "nb_avec_opp_ouverte": len(avec_pipe),
            "pipe_ouvert_xof": round(sum(c["opp_ouvertes_xof"] for c in avec_pipe)),
            "silence_median_mois": _median(silences),
            "comptes": [
                _fiche(c) for c in sorted(lot, key=lambda x: -x["ca_total_xof"])[:top_n]
            ],
        })

    # ── Décrochages : le cœur du suivi d'état ─────────────────────────────────
    # Comptes Ralentit + Dormant, par CA historique décroissant. Répond à
    # « quels comptes qui comptaient viennent de se taire ».
    decroches = [c for c in enrichis if c["segment"] in _SEGMENTS_DECROCHAGE]
    decrochages = [
        _fiche(c) for c in sorted(decroches, key=lambda x: -x["ca_total_xof"])[:top_n]
    ]

    dormants_impaye = [
        c for c in enrichis if c["segment"] in _SEGMENTS_SOMMEIL and c["alerte_impaye"]
    ]
    ca_sommeil = sum(
        c["ca_total_xof"] for c in enrichis if c["segment"] in _SEGMENTS_SOMMEIL
    )
    hors_ref = [c for c in enrichis if c["hors_referentiel"]]
    ca_nul = [c for c in enrichis if c["nb_commandes"] > 0 and c["ca_total_xof"] <= 0]

    return {
        "as_of": today.isoformat(),
        "seuils_mois": {
            "ralentit": _SEUIL_RALENTIT_MOIS,
            "dormant": _SEUIL_DORMANT_MOIS,
            "perdu": _SEUIL_PERDU_MOIS,
        },
        "segments": segments,
        "decrochages": decrochages,
        "totaux": {
            "nb_comptes": nb_total,
            "nb_avec_commande": sum(1 for c in enrichis if c["segment"] != "prospect"),
            "nb_prospects": sum(1 for c in enrichis if c["segment"] == "prospect"),
            "ca_historique_xof": round(ca_total),
            # CA des comptes Ralentit + Dormant : ce qui vient de sortir du radar et
            # reste récupérable, par opposition au « sommeil » (Dormant + Perdu).
            "ca_a_risque_xof": round(
                sum(c["ca_total_xof"] for c in enrichis if c["segment"] in _SEGMENTS_DECROCHAGE)
            ),
            "nb_decroches": len(decroches),
        },
        # Historique CUMULÉ des comptes sortis du radar — jamais un manque à gagner
        # de l'exercice. Le front doit le qualifier, sinon le montant se lit comme
        # une perte annuelle.
        "sommeil": {
            "ca_historique_xof": round(ca_sommeil),
            "part_ca_pct": _pct(ca_sommeil, ca_total),
            "nb_comptes": sum(1 for c in enrichis if c["segment"] in _SEGMENTS_SOMMEIL),
        },
        "dormants_avec_impaye": {
            "nb_comptes": len(dormants_impaye),
            "impaye_xof": round(sum(c["impaye_xof"] for c in dormants_impaye)),
            "comptes": [
                _fiche(c) for c in sorted(dormants_impaye, key=lambda x: -x["impaye_xof"])[:top_n]
            ],
        },
        # Anomalies du miroir remontées plutôt que masquées : elles se corrigent dans
        # Odoo, pas dans le cockpit, et le DC est le mieux placé pour les faire traiter.
        "qualite_donnees": {
            "nb_hors_referentiel": len(hors_ref),
            "ca_hors_referentiel_xof": round(sum(c["ca_total_xof"] for c in hors_ref)),
            "nb_comptes_ca_nul": len(ca_nul),
        },
        "note": _NOTE,
    }
