"""Fichier de visite — §6 du compte-rendu DC. GABARIT assumé.

« Mise en place d'un fichier de visite permettant d'historiser les visites
clients. Chaque visite doit pouvoir être documentée par un compte-rendu de visite
directement intégré à l'outil. »

Aucune table de visite n'existe dans le système. Ce module sert la FORME de
l'écran pour trancher les questions 43 à 47 du cadrage sur du concret : qui
saisit, quand, quel contenu minimal, faut-il lire les comptes rendus ou seulement
suivre un taux de couverture, une visite se rattache-t-elle à un compte ou à une
opportunité.

Le module est explicitement `mixte`, et c'est le point important :

- les VISITES sont posées à la main (cf. `statique.VISITES_STATIQUES`) ;
- les COMPTES à visiter, eux, sont RÉELS — tirés du portefeuille, de leur CA et de
  leur dernière commande. C'est la moitié utile dès aujourd'hui : « ce compte n'a
  pas été visité depuis quatre mois » n'est pas mesurable, mais « ce compte à
  4 274 M FCFA n'a pas commandé depuis onze mois » l'est.

Rappel de périmètre porté par le retour : il s'agit d'un module de SAISIE destiné
aux commerciaux, pas d'un indicateur de pilotage. Le traiter séparément permet de
livrer plus vite sur le cockpit lui-même.
"""
from __future__ import annotations

from datetime import date, datetime

from modules.uc_commercial import statique


def _parse_date(valeur: str | None) -> date | None:
    if not valeur:
        return None
    try:
        return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _mois_ecoules(depuis: date, jusqu_a: date) -> int:
    return max(0, (jusqu_a.year - depuis.year) * 12 + (jusqu_a.month - depuis.month))


def build_fichier_visites(comptes: list[dict], today: date | None = None, limit: int = 12) -> dict:
    """Fichier de visite (gabarit) + comptes à couvrir (réels)."""
    jour = today or date.today()

    visites = []
    for v in statique.VISITES_STATIQUES:
        d = _parse_date(v["date"])
        visites.append({
            **v,
            "mois_ecoules": _mois_ecoules(d, jour) if d else None,
            "exemple": True,
        })
    visites.sort(key=lambda v: v["date"], reverse=True)

    # Rapprochement par nom en MAJUSCULES : le gabarit ne porte pas de client_id,
    # et c'est cohérent avec ce que saisirait un commercial — il tape un nom de
    # compte, pas un identifiant Odoo. Un vrai module de saisie devra, lui,
    # rattacher un client_id (sinon les visites se dispersent sur les orthographes).
    visites_par_compte = {(v["compte"] or "").strip().upper(): v for v in visites}

    actifs = [c for c in comptes if c.get("ca_total_xof", 0) > 0]
    couverts, a_visiter = [], []
    for c in sorted(actifs, key=lambda c: -c.get("ca_total_xof", 0)):
        visite = visites_par_compte.get((c.get("compte") or "").strip().upper())
        derniere_commande = _parse_date(c.get("derniere_commande"))
        ligne = {
            "compte": c.get("compte"),
            "client_id": c.get("client_id"),
            "commercial": c.get("commercial") or "",
            "ca_total_xof": c.get("ca_total_xof", 0),
            "derniere_commande": c.get("derniere_commande"),
            "mois_silence": _mois_ecoules(derniere_commande, jour) if derniere_commande else None,
            "nb_opp_ouvertes": c.get("nb_opp_ouvertes", 0),
            "derniere_visite": visite["date"] if visite else None,
            "mois_depuis_visite": visite["mois_ecoules"] if visite else None,
        }
        if visite:
            couverts.append(ligne)
        else:
            a_visiter.append(ligne)

    nb_actifs = len(actifs)
    return {
        "source": statique.SOURCE_MIXTE,
        "raison": statique.RAISON_VISITES_STATIQUE,
        "avertissement": statique.AVERTISSEMENT_STATIQUE,
        "as_of": jour.isoformat(),
        "seuil_couverture_mois": statique.SEUIL_COUVERTURE_VISITE_MOIS,
        "visites": visites,
        "comptes_a_visiter": a_visiter[:limit],
        "comptes_couverts": couverts,
        "couverture": {
            "source": statique.SOURCE_MIXTE,
            "nb_comptes_actifs": nb_actifs,
            "nb_visites_enregistrees": len(visites),
            "nb_comptes_couverts": len(couverts),
            "nb_comptes_sans_visite": len(a_visiter),
            "taux_couverture_pct": round(100 * len(couverts) / nb_actifs, 1) if nb_actifs else 0.0,
            "lecture": (
                "Le taux de couverture est un gabarit : il compare des comptes réels à des visites posées "
                "à la main. Il devient un indicateur le jour où les visites sont saisies."
            ),
        },
        "contenu_minimal": [
            "date de la visite",
            "compte visité",
            "interlocuteur rencontré (fonction, et non le seul nom)",
            "objet de la visite",
            "prochaine action et sa date",
            "opportunité rattachée, si la visite en concerne une",
        ],
        "questions_ouvertes": [
            "Qui saisit le compte rendu : le commercial, l'account manager, la direction ?",
            "Quand : au retour de visite depuis un mobile, ou le soir au bureau ?",
            "Faut-il lire les comptes rendus, ou seulement suivre le taux de couverture ?",
            "Une visite se rattache-t-elle à un compte seulement, ou aussi à une opportunité ?",
        ],
    }
