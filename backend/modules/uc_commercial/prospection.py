"""Efficacité commerciale et indice de prospection — §3 du compte-rendu DC.

Deux indicateurs de nature opposée, réunis ici parce qu'ils répondent à la même
question du DC (« comparer objectivement les performances entre commerciaux ») :

- L'INDICE D'EFFICACITÉ est entièrement MESURABLE. Les issues gagné/perdu et les
  montants existent dans le miroir ; ce qui manquait, c'est une identité stable
  par commercial — fournie par `referentiel.py`.
- L'INDICE DE PROSPECTION ne l'est pas. Il compte « les opportunités générées, par
  mois, par trimestre et par an » : c'est une mesure de FLUX, et le miroir ne
  porte pas de date de création exploitable (deux imports en masse concentrent
  6 475 créations sur deux journées). Il est servi en gabarit, marqué comme tel.

Sur l'efficacité, le cadrage laisse trois questions ouvertes (25 à 28) : quel
numérateur, faut-il pondérer par le montant, faut-il neutraliser le portefeuille
hérité. Aucune n'est tranchée ici à la place du DC — l'indice expose donc SES
composantes, et chaque colonne reste lisible séparément. Un indice unique dont on
ne peut pas ouvrir le calcul ne se conteste pas : il se subit.

Précaution imposée par les données : les taux de transformation portent sur
l'HISTORIQUE COMPLET (les opportunités n'ont pas de date fiable), tandis que le CA
signé porte sur l'année demandée. Deux périodes sur une même ligne, donc deux
en-têtes distincts à l'écran — les confondre ferait passer un commercial arrivé
récemment pour un mauvais transformateur.
"""
from __future__ import annotations

from modules.uc_commercial import statique
from modules.uc_commercial.comptes import est_ouverte
from modules.uc_commercial.objectifs import LIBELLES_MOIS
from modules.uc_commercial.referentiel import normaliser, resoudre


# En dessous de ce nombre d'affaires closes, un taux de transformation n'est pas
# un indicateur mais un accident d'échantillon : sur ce miroir, plusieurs
# porteurs affichent 100 % en valeur avec zéro affaire perdue, ce qui les
# placerait en tête d'un classement qu'ils n'ont pas gagné. Leur taux reste
# affiché (il est vrai) mais n'entre pas dans l'indice, et `taux_significatif`
# le dit à l'écran.
MIN_CLOSES_POUR_TAUX = 8


def _issue(stage: str | None) -> str:
    s = (stage or "").lower()
    if any(p in s for p in ("gagn", "won")):
        return "gagnee"
    if any(p in s for p in ("perdu", "lost")):
        return "perdue"
    if any(p in s for p in ("annul", "cancel")):
        return "annulee"
    return "ouverte"


def _rangs(valeurs: dict[str, float]) -> dict[str, float]:
    if not valeurs:
        return {}
    ordonne = sorted(valeurs.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ordonne)
    if n == 1:
        return {ordonne[0][0]: 100.0}
    return {cle: round(100 * (n - 1 - i) / (n - 1), 1) for i, (cle, _) in enumerate(ordonne)}


def build_efficacite(
    opportunites: list[dict],
    ca_annee: list[dict],
    index_resolution: dict,
    referentiel: dict,
    lignes_sans_commercial: dict,
    annee: int,
    limit: int = 20,
) -> dict:
    """Indice d'efficacité par commercial, composantes exposées une à une."""
    agg: dict[str, dict] = {}
    exclus: dict[str, dict] = {}

    def _entree(nom: str) -> dict | None:
        resolu = resoudre(index_resolution, nom)
        cible = exclus if resolu["nature"] in ("technique", "collectif") else agg
        cle = resolu["salesperson_id"] or normaliser(nom)
        e = cible.setdefault(cle, {
            "salesperson_id": resolu["salesperson_id"],
            "display_name": resolu["display_name"],
            "nature": resolu["nature"],
            "nb_gagnees": 0, "nb_perdues": 0, "nb_ouvertes": 0,
            "montant_gagne_xof": 0, "montant_perdu_xof": 0, "pipe_ouvert_xof": 0,
            "ca_signe_xof": 0, "nb_commandes": 0,
        })
        return e

    for o in opportunites:
        e = _entree(o.get("commercial") or "")
        if e is None:
            continue
        issue = _issue(o.get("stage"))
        montant = o.get("montant_xof", 0)
        if issue == "gagnee":
            e["nb_gagnees"] += 1
            e["montant_gagne_xof"] += montant
        elif issue == "perdue":
            e["nb_perdues"] += 1
            e["montant_perdu_xof"] += montant
        elif est_ouverte(o.get("stage")):
            e["nb_ouvertes"] += 1
            e["pipe_ouvert_xof"] += montant

    for l in ca_annee:
        e = _entree(l["commercial"])
        if e is None:
            continue
        e["ca_signe_xof"] += l["ca_xof"]
        e["nb_commandes"] += l["nb"]

    def _finalise(source: dict) -> list[dict]:
        lignes = []
        for cle, e in source.items():
            nb_closes = e["nb_gagnees"] + e["nb_perdues"]
            valeur_engagee = e["montant_gagne_xof"] + e["montant_perdu_xof"]
            lignes.append({
                **e,
                "cle": cle,
                "nb_closes": nb_closes,
                "taux_significatif": nb_closes >= MIN_CLOSES_POUR_TAUX,
                "taux_nb_pct": round(100 * e["nb_gagnees"] / nb_closes, 1) if nb_closes else None,
                "taux_valeur_pct": round(100 * e["montant_gagne_xof"] / valeur_engagee, 1) if valeur_engagee else None,
                "panier_moyen_xof": round(e["ca_signe_xof"] / e["nb_commandes"]) if e["nb_commandes"] else 0,
                "ticket_moyen_gagne_xof": round(e["montant_gagne_xof"] / e["nb_gagnees"]) if e["nb_gagnees"] else 0,
            })
        return lignes

    lignes = _finalise(agg)
    lignes_exclues = _finalise(exclus)

    # L'indice combine trois composantes de NATURES différentes, par rang :
    # transformation (taux en valeur), volume signé (CA), et taille d'affaire
    # (ticket moyen gagné). Le rang évite de mélanger des pourcentages et des
    # francs dans une même moyenne — et répond à la question 26 du cadrage sans
    # la trancher : peu de grosses affaires et beaucoup de petites peuvent aboutir
    # au même indice, mais les colonnes disent laquelle des deux.
    #
    # Un commercial sans affaire close est classé sur ses deux autres composantes
    # seulement : lui attribuer un taux de 0 % le punirait d'être nouveau. Même
    # traitement au-dessus de zéro mais sous le seuil de significativité — un
    # 100 % sur trois affaires n'est pas une performance mesurée.
    r_taux = _rangs({
        l["cle"]: l["taux_valeur_pct"]
        for l in lignes if l["taux_valeur_pct"] is not None and l["taux_significatif"]
    })
    r_ca = _rangs({l["cle"]: float(l["ca_signe_xof"]) for l in lignes})
    r_ticket = _rangs({l["cle"]: float(l["ticket_moyen_gagne_xof"]) for l in lignes})
    for l in lignes:
        composantes = [r for r in (r_taux.get(l["cle"]), r_ca.get(l["cle"]), r_ticket.get(l["cle"])) if r is not None]
        l["indice_efficacite"] = round(sum(composantes) / len(composantes), 1) if composantes else None
        l["composantes"] = {
            "transformation": r_taux.get(l["cle"]),
            "volume_signe": r_ca.get(l["cle"]),
            "taille_affaire": r_ticket.get(l["cle"]),
        }

    lignes.sort(key=lambda l: (l["indice_efficacite"] is None, -(l["indice_efficacite"] or 0)))
    for i, l in enumerate(lignes, start=1):
        l["rang"] = i
    lignes_exclues.sort(key=lambda l: -l["ca_signe_xof"])

    alias_non_confirmes = sum(1 for a in referentiel.get("alias", []) if not a.get("confirmed", False))
    ca_nominatif = sum(l["ca_signe_xof"] for l in lignes)
    ca_total = ca_nominatif + sum(l["ca_signe_xof"] for l in lignes_exclues)

    return {
        "source": statique.SOURCE_REELLE,
        "annee": annee,
        "commerciaux": lignes[:limit],
        "porteurs_non_nominatifs": lignes_exclues,
        "periodes_mesure": {
            "transformation": "historique complet du miroir (les opportunités ne portent pas de date fiable)",
            "ca_signe": f"commandes signées de {annee}",
        },
        "fiabilite": {
            "nb_orthographes_observees": referentiel["totaux"]["nb_orthographes_observees"],
            "nb_personnes": referentiel["totaux"]["nb_personnes"],
            "nb_doublons_orthographe": referentiel["totaux"]["nb_doublons_orthographe"],
            "nb_non_nominatifs": referentiel["totaux"]["nb_non_nominatifs"],
            "nb_alias_non_confirmes": alias_non_confirmes,
            "nb_opportunites_sans_commercial": lignes_sans_commercial.get("opportunites", 0),
            "nb_commandes_sans_commercial": lignes_sans_commercial.get("commandes", 0),
            "part_ca_nominative_pct": round(100 * ca_nominatif / ca_total, 1) if ca_total else 0.0,
            "avertissement": (
                "Les commerciaux sont stockés en texte libre dans l'ERP, sans référentiel : les identités "
                "ci-dessus sont un rapprochement automatique des orthographes, non encore validé "
                "humainement. Tant qu'il ne l'est pas, le classement est indicatif."
            ),
        },
        "limites": [
            "Le portefeuille hérité n'est pas neutralisé : un commercial sur grands comptes historiques "
            "n'est pas comparable à un chasseur de nouveaux clients (question 28 du cadrage).",
            "Le numérateur et le dénominateur de l'« indice d'efficacité » n'ont pas été tranchés par la "
            "Direction Commerciale : les trois composantes sont donc affichées séparément.",
        ],
        "note": (
            "Indice calculé sur les rangs de trois composantes — transformation en valeur, volume signé, "
            "taille moyenne des affaires gagnées. Un commercial sans affaire close n'est pas pénalisé "
            f"d'un taux de 0 % : il est classé sur ses composantes disponibles. Sous {MIN_CLOSES_POUR_TAUX} "
            "affaires closes, le taux de transformation reste affiché mais n'entre pas dans l'indice — "
            "un 100 % obtenu sur trois affaires n'est pas une performance mesurée."
        ),
        "seuil_significativite_closes": MIN_CLOSES_POUR_TAUX,
    }


def build_indice_prospection(annee: int, periode: str = "mois", objectif_leads: int | None = None) -> dict:
    """Indice de prospection — GABARIT : la donnée de flux n'existe pas.

    La forme est celle demandée (mensuel, trimestriel, annuel, avec l'objectif de
    volume et le focus nouveaux comptes). Les valeurs sont posées ; `source` et
    `raison` le disent, et le front doit l'afficher.
    """
    objectif = objectif_leads or statique.OBJECTIF_LEADS_ANNUEL
    serie = statique.PROSPECTION_MENSUELLE_STATIQUE

    if periode == "trimestre":
        lignes = []
        for t in range(1, 5):
            mois = [m for m in serie if (m["mois"] - 1) // 3 + 1 == t]
            lignes.append({
                "index": t,
                "libelle": f"T{t} {annee}",
                "nb_opportunites": sum(m["nb_opportunites"] for m in mois),
                "nb_nouveaux_comptes": sum(m["nb_nouveaux_comptes"] for m in mois),
                "montant_genere_xof": sum(m["montant_genere_xof"] for m in mois),
            })
    elif periode == "annee":
        lignes = [{
            "index": 0,
            "libelle": str(annee),
            "nb_opportunites": sum(m["nb_opportunites"] for m in serie),
            "nb_nouveaux_comptes": sum(m["nb_nouveaux_comptes"] for m in serie),
            "montant_genere_xof": sum(m["montant_genere_xof"] for m in serie),
        }]
    else:
        lignes = [{
            "index": m["mois"],
            "libelle": f"{LIBELLES_MOIS[m['mois'] - 1].capitalize()} {annee}",
            "nb_opportunites": m["nb_opportunites"],
            "nb_nouveaux_comptes": m["nb_nouveaux_comptes"],
            "montant_genere_xof": m["montant_genere_xof"],
        } for m in serie]

    total_opp = sum(m["nb_opportunites"] for m in serie)
    for l in lignes:
        part = l["nb_opportunites"] / total_opp if total_opp else 0
        cible = objectif * part
        l["objectif_nb"] = round(cible)
        l["ecart_nb"] = l["nb_opportunites"] - round(cible)

    return {
        "source": statique.SOURCE_STATIQUE,
        "raison": statique.RAISON_PROSPECTION_STATIQUE,
        "avertissement": statique.AVERTISSEMENT_STATIQUE,
        "annee": annee,
        "periode": periode,
        "objectif_annuel_nb": objectif,
        "lignes": lignes,
        "totaux": {
            "nb_opportunites": total_opp,
            "nb_nouveaux_comptes": sum(m["nb_nouveaux_comptes"] for m in serie),
            "montant_genere_xof": sum(m["montant_genere_xof"] for m in serie),
            "taux_atteinte_pct": round(100 * total_opp / objectif, 1) if objectif else None,
        },
        "note": (
            "Le volume de leads annuel à générer était illisible sur la note manuscrite de l'entretien : "
            f"la valeur de {objectif} retenue ici est à reconfirmer. Par ailleurs, aucune table de leads "
            "n'existe — un objectif exprimé en leads ne sera pas mesurable avant que l'amont de "
            "l'opportunité soit remonté de l'ERP."
        ),
    }
