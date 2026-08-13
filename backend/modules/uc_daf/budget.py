"""Tableau de bord n°1 — Budget : performance, résultat net, marge brute, charges, lignes budgétaires.

Demande du DAF, dans l'ordre de sa note : « Performance (indicateur global).
Résultat net. Marge brute réalisée à date. Top 10 des plus grosses charges —
indicateur validé ("Voté"). Lignes budgétaires les plus consommées. »

Cinq indicateurs, quatre régimes de faisabilité différents. C'est ce que cet écran
doit rendre lisible, faute de quoi il livrerait cinq chiffres d'apparence
équivalente dont deux seulement sont mesurés :

1. MARGE BRUTE RÉALISÉE : MESURÉE, mais sous condition de couverture. Les dossiers
   portent CA et dépense définitifs — sauf que 1 424 sur 2 408 n'ont aucune dépense
   imputée, et un dossier sans dépense affiche 100 % de marge. Le module ne
   moyenne donc jamais l'ensemble : il calcule sur le périmètre imputé, publie sa
   couverture, et refuse de qualifier le taux d'exploitable en dessous d'un seuil.
   Sur l'exercice 2026 la couverture est quasi nulle : le taux est alors servi
   `exploitable: false` plutôt que servi flatteur.

2. TOP 10 DES CHARGES : MESURÉ. Les 2 133 commandes d'achat donnent le classement
   réel des fournisseurs. Une réserve de périmètre est portée à l'écran : ce sont
   les achats, pas toutes les charges — la masse salariale n'est pas dans le miroir
   et resterait la première ligne de tout classement de charges d'une ESN.

3. LIGNES BUDGÉTAIRES : MIXTE. Le budget voté n'existe nulle part (c'est une
   décision), la consommation est mesurée sur les achats réels rattachés par une
   grille de motifs éditable. Budget posé, consommé mesuré, jamais fondus.

4. RÉSULTAT NET : PROJECTION. Aucune comptabilité générale n'est raccordée. Marge
   brute mesurée moins charges de structure posées moins impôt posé : trois champs
   distincts, un total nommé « projection ».

5. PERFORMANCE : COMPOSITE EXPLICITE. Indicateur demandé sans définition. Plutôt
   que d'inventer un score opaque, quatre composantes mesurées sont rapportées à
   des cibles posées, avec leurs poids affichés — le DAF peut contester la
   pondération, ce qu'un score fermé ne permet pas.
"""
from __future__ import annotations

import unicodedata
from datetime import date

from modules.uc_daf import statique
from modules.uc_daf.commun import (
    jour,
    libelle_mois,
    part_ecoulee_exercice_pct,
    pct,
    taux_atteinte_pct,
)

# Couverture minimale de dépense imputée en dessous de laquelle le taux de marge
# n'est pas déclaré exploitable. Même principe que `duree_close.exploitable` du
# cycle de vie DC : mieux vaut publier la couverture que le chiffre.
COUVERTURE_MARGE_MIN_PCT = 40.0

# Nombre de charges au classement — « top 10 » est la demande littérale du DAF.
TOP_CHARGES = 10


def normaliser(texte: str) -> str:
    """Minuscules sans accent, encadré d'espaces — pour la recherche de motifs.

    Repris de `uc_commercial.marche` : les espaces encadrants permettent d'écrire
    un motif « mot entier » (` sarl `) sans capter les mots qui le contiennent.
    """
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn"
    )
    return f" {' '.join(sans_accent.lower().split())} "


def classer_ligne_budgetaire(fournisseur: str, lignes: list[dict] | None = None) -> tuple[str, str | None]:
    """Ligne budgétaire d'un achat, d'après le nom du fournisseur.

    Renvoie `(ligne, motif)` — le motif est conservé pour que l'écran puisse
    montrer POURQUOI un achat a été rattaché là. Un rattachement qu'on ne peut pas
    justifier n'est pas arbitrable par le DAF.

    La ligne de recueil (`statique.LIGNE_RECUEIL`) attrape ce qu'aucun motif ne
    reconnaît, avec `motif = None` : c'est ce qui distingue « classé dans les frais
    généraux » de « pas encore classé ».
    """
    grille = lignes if lignes is not None else statique.BUDGET_LIGNES
    cible = normaliser(fournisseur)
    for ligne in sorted(grille, key=lambda l: l["priority"]):
        for motif in ligne["motifs"]:
            if normaliser(motif).strip() in cible:
                return ligne["ligne"], motif
    return statique.LIGNE_RECUEIL, None


# ── Marge brute réalisée à date ──────────────────────────────────────────────

def build_marge_brute(dossiers: list[dict], achats: list[dict], ca_mensuel: list[dict],
                      annee: int, aujourdhui: date) -> dict:
    """Marge brute mesurée, en DEUX lectures — par dossier et sur les flux engagés.

    La lecture par DOSSIER est la bonne : elle rapporte le CA définitif d'une
    affaire à la dépense qui l'a servie. Mais elle n'est exploitable que si la
    dépense est imputée, et sur l'exercice 2026 elle ne l'est que sur 2 dossiers
    sur 238 — soit 0,5 % du CA. Publier ce taux (96,7 %) comme « marge brute
    réalisée » aurait été un chiffre faux et flatteur.

    La lecture sur FLUX ENGAGÉS existe donc à côté : CA signé de l'exercice moins
    achats engagés sur la même période, tous deux mesurés et complets. Elle est
    plus grossière — un achat de décembre sert parfois un projet de l'année
    suivante, et les charges internes n'y sont pas — mais elle couvre 100 % de
    l'activité et reste vraie à l'échelle de l'exercice.

    Les deux sont servies, nommées, et `lecture_retenue` dit laquelle porte
    l'indicateur affiché. Le périmètre retenu pour la lecture par dossier est celui
    des dossiers dont la DÉPENSE DÉFINITIVE est imputée : inclure les autres
    reviendrait à compter leur CA sans leur coût.
    """
    de_lexercice = [d for d in dossiers if (jour(d["cree_le"]) or date(1900, 1, 1)).year == annee]
    imputes = [d for d in de_lexercice if d["depense_definitive_xof"] > 0]

    ca_impute = sum(d["ca_definitif_xof"] for d in imputes)
    depense_imputee = sum(d["depense_definitive_xof"] for d in imputes)
    marge_imputee = ca_impute - depense_imputee

    ca_exercice = sum(d["ca_definitif_xof"] for d in de_lexercice)
    couverture_pct = pct(ca_impute, ca_exercice)
    exploitable = bool(imputes) and couverture_pct >= COUVERTURE_MARGE_MIN_PCT

    # Série mensuelle sur le périmètre imputé uniquement : un mois sans dépense
    # imputée afficherait 100 % de marge et ferait un pic absurde sur le graphe.
    par_mois: dict[int, dict] = {}
    for d in imputes:
        cree = jour(d["cree_le"])
        if not cree:
            continue
        ligne = par_mois.setdefault(cree.month, {"ca_xof": 0, "depense_xof": 0, "nb_dossiers": 0})
        ligne["ca_xof"] += d["ca_definitif_xof"]
        ligne["depense_xof"] += d["depense_definitive_xof"]
        ligne["nb_dossiers"] += 1

    serie = []
    for mois in range(1, 13):
        ligne = par_mois.get(mois)
        if not ligne and (annee, mois) > (aujourdhui.year, aujourdhui.month):
            continue
        ca = ligne["ca_xof"] if ligne else 0
        depense = ligne["depense_xof"] if ligne else 0
        serie.append({
            "mois": mois,
            "libelle": libelle_mois(annee, mois, court=True),
            "ca_xof": ca,
            "depense_xof": depense,
            "marge_xof": ca - depense,
            "taux_pct": pct(ca - depense, ca),
            "nb_dossiers": ligne["nb_dossiers"] if ligne else 0,
        })

    # ── Lecture sur flux engagés : mesurée et complète, plus grossière ──
    ca_signe = sum(m["ca_xof"] for m in ca_mensuel)
    achats_exercice = [a for a in achats if (jour(a["date"]) or date(1900, 1, 1)).year == annee]
    achats_engages = sum(a["montant_xof"] for a in achats_exercice)
    lecture_flux = {
        "ca_signe_xof": ca_signe,
        "achats_engages_xof": achats_engages,
        "marge_xof": ca_signe - achats_engages,
        "taux_pct": pct(ca_signe - achats_engages, ca_signe),
        "nb_commandes_vente": sum(m["nb_commandes"] for m in ca_mensuel),
        "nb_commandes_achat": len(achats_exercice),
        "limites": (
            "Marge de flux, pas marge de dossier : un achat engagé en fin d'exercice sert parfois un "
            "projet de l'exercice suivant, et les coûts internes (temps passé, licences mutualisées) "
            "n'y figurent pas. Elle couvre en revanche 100 % de l'activité, là où la lecture par "
            "dossier dépend de l'imputation des dépenses."
        ),
    }
    lecture_retenue = "dossiers" if exploitable else "flux"
    marge_retenue = marge_imputee if exploitable else lecture_flux["marge_xof"]
    ca_retenu = ca_impute if exploitable else ca_signe
    # `None` et non `0` quand l'exercice ne porte aucun CA : un taux de marge de
    # 0 % se lirait comme une catastrophe et pèserait comme telle dans l'indice de
    # performance, alors qu'il n'y a simplement rien à mesurer.
    taux_retenu = (
        (pct(marge_imputee, ca_impute) if exploitable else lecture_flux["taux_pct"])
        if ca_retenu else None
    )

    return {
        "source": statique.SOURCE_REELLE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "ca_realise_xof": ca_impute,
        "depenses_xof": depense_imputee,
        "marge_xof": marge_imputee,
        "taux_pct": pct(marge_imputee, ca_impute),
        # Ce que l'écran doit afficher en grand, et sur quelle base il l'a calculé.
        "lecture_retenue": lecture_retenue,
        "marge_retenue_xof": marge_retenue,
        "ca_retenu_xof": ca_retenu,
        "taux_retenu_pct": taux_retenu,
        "lecture_flux": lecture_flux,
        "cible_taux_pct": statique.CIBLES_PERFORMANCE["marge_brute_pct"],
        "marge_provisoire_xof": sum(d["marge_provisoire_xof"] for d in de_lexercice),
        "ca_provisoire_xof": sum(d["ca_provisoire_xof"] for d in de_lexercice),
        "taux_provisoire_pct": pct(
            sum(d["marge_provisoire_xof"] for d in de_lexercice),
            sum(d["ca_provisoire_xof"] for d in de_lexercice),
        ),
        "couverture": {
            "nb_dossiers_exercice": len(de_lexercice),
            "nb_dossiers_imputes": len(imputes),
            "ca_exercice_xof": ca_exercice,
            "ca_impute_xof": ca_impute,
            "couverture_pct": couverture_pct,
            "seuil_exploitable_pct": COUVERTURE_MARGE_MIN_PCT,
            "exploitable": exploitable,
            "raison_non_exploitable": (
                ""
                if exploitable
                else (
                    f"{len(de_lexercice) - len(imputes)} dossiers sur {len(de_lexercice)} de l'exercice "
                    f"{annee} n'ont aucune dépense définitive imputée, soit une couverture de "
                    f"{couverture_pct:.1f} % du CA (seuil retenu : {COUVERTURE_MARGE_MIN_PCT:.0f} %). "
                    "Le taux calculé sur le seul périmètre imputé n'est pas représentatif de "
                    "l'exercice — c'est un problème d'imputation, pas de rentabilité."
                )
            ),
        },
        "serie_mensuelle": serie,
        "note": (
            "Deux lectures mesurées, jamais fondues. PAR DOSSIER : CA définitif moins dépense "
            "définitive, sur les seuls dossiers dont la dépense est imputée — un dossier sans dépense "
            "afficherait 100 % de marge, il est donc exclu du calcul et compté dans la couverture. "
            "SUR FLUX ENGAGÉS : CA signé moins achats engagés de l'exercice, complet mais plus "
            "grossier. La lecture par dossier prime dès que sa couverture le permet ; en dessous du "
            f"seuil de {COUVERTURE_MARGE_MIN_PCT:.0f} %, l'indicateur bascule sur les flux et le dit."
        ),
    }


# ── Top des charges ─────────────────────────────────────────────────────────

def build_top_charges(achats: list[dict], annee: int, aujourdhui: date, limit: int = TOP_CHARGES) -> dict:
    """Classement des charges par fournisseur — mesuré sur les achats engagés.

    Indicateur « Voté » dans la note du DAF : il est servi tel quel, avec sa
    réserve de périmètre. Les achats ne sont pas toutes les charges — la masse
    salariale, premier poste de toute ESN, n'est pas dans le miroir. Le dire à
    l'écran évite qu'un « top 10 des charges » soit lu comme exhaustif.
    """
    de_lexercice = [a for a in achats if (jour(a["date"]) or date(1900, 1, 1)).year == annee]
    total = sum(a["montant_xof"] for a in de_lexercice)

    par_fournisseur: dict[str, dict] = {}
    for a in de_lexercice:
        f = par_fournisseur.setdefault(a["fournisseur"], {
            "fournisseur": a["fournisseur"], "montant_xof": 0, "nb_commandes": 0,
            "derniere_commande": None, "devises": set(), "ligne_budgetaire": None,
        })
        f["montant_xof"] += a["montant_xof"]
        f["nb_commandes"] += 1
        f["devises"].add(a["devise"])
        if a["date"] and (f["derniere_commande"] is None or a["date"] > f["derniere_commande"]):
            f["derniere_commande"] = a["date"]
        f["ligne_budgetaire"] = classer_ligne_budgetaire(a["fournisseur"])[0]

    classes = sorted(par_fournisseur.values(), key=lambda f: -f["montant_xof"])
    charges, cumul = [], 0
    for rang, f in enumerate(classes[:limit], start=1):
        cumul += f["montant_xof"]
        charges.append({
            "rang": rang,
            "fournisseur": f["fournisseur"],
            "montant_xof": f["montant_xof"],
            "nb_commandes": f["nb_commandes"],
            "montant_moyen_xof": round(f["montant_xof"] / f["nb_commandes"]) if f["nb_commandes"] else 0,
            "part_pct": pct(f["montant_xof"], total),
            "part_cumulee_pct": pct(cumul, total),
            "derniere_commande": f["derniere_commande"],
            "devises": sorted(f["devises"]),
            "ligne_budgetaire": f["ligne_budgetaire"],
        })

    n1 = [a for a in achats if (jour(a["date"]) or date(1900, 1, 1)).year == annee - 1]
    total_n1 = sum(a["montant_xof"] for a in n1)
    return {
        "source": statique.SOURCE_REELLE,
        # Marqueur de la note du DAF (« Voté ») : cet indicateur est validé, il ne
        # fait pas partie des points restés à confirmer.
        "valide_par_daf": True,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "charges": charges,
        "totaux": {
            "montant_total_xof": total,
            "nb_fournisseurs": len(par_fournisseur),
            "nb_commandes": len(de_lexercice),
            "part_top_pct": pct(cumul, total),
            "montant_top_xof": cumul,
            "montant_exercice_precedent_xof": total_n1,
            "variation_pct": pct(total - total_n1, total_n1) if total_n1 else None,
            "nb_commandes_en_devise": sum(1 for a in de_lexercice if a["devise"] != "XOF"),
        },
        "perimetre": (
            "Achats fournisseurs ENGAGÉS (commandes confirmées) de l'exercice. Ce n'est pas "
            "l'intégralité des charges : masse salariale, loyers, énergie et amortissements ne sont "
            "dans aucune table du système. Sur une ESN, la masse salariale serait la première ligne "
            "de ce classement."
        ),
        "note": (
            "Montants pris dans la devise de la société. Les commandes libellées en devise étrangère "
            "sont converties par l'ERP, mais le taux appliqué n'est pas conservé dans le miroir : "
            "leur nombre est remonté pour que le classement puisse être contesté à la marge."
        ),
    }


# ── Lignes budgétaires ──────────────────────────────────────────────────────

def build_lignes_budgetaires(achats: list[dict], annee: int, aujourdhui: date) -> dict:
    """Consommation mesurée contre budget posé, ligne par ligne.

    Le taux de consommation n'est JAMAIS publié seul : il est toujours accompagné
    de la part d'exercice écoulée. Une ligne à 80 % en février est une alerte, la
    même à 80 % en novembre est normale — sans ce repère, l'écran fabrique de
    fausses urgences et en masque de vraies.
    """
    part_ecoulee = part_ecoulee_exercice_pct(annee, aujourdhui)
    de_lexercice = [a for a in achats if (jour(a["date"]) or date(1900, 1, 1)).year == annee]

    consommation: dict[str, dict] = {
        l["ligne"]: {
            "ligne": l["ligne"],
            "budget_annuel_xof": l["budget_annuel_xof"],
            "commentaire": l["commentaire"],
            "motifs": l["motifs"],
            "consomme_xof": 0,
            "nb_commandes": 0,
            "fournisseurs": {},
            "motifs_utilises": set(),
        }
        for l in statique.BUDGET_LIGNES
    }

    for a in de_lexercice:
        nom_ligne, motif = classer_ligne_budgetaire(a["fournisseur"])
        ligne = consommation[nom_ligne]
        ligne["consomme_xof"] += a["montant_xof"]
        ligne["nb_commandes"] += 1
        ligne["fournisseurs"][a["fournisseur"]] = ligne["fournisseurs"].get(a["fournisseur"], 0) + a["montant_xof"]
        if motif:
            ligne["motifs_utilises"].add(motif)

    lignes = []
    for l in consommation.values():
        budget = l["budget_annuel_xof"]
        consomme = l["consomme_xof"]
        taux = pct(consomme, budget)
        # Le statut compare la consommation à la part d'exercice écoulée, pas à
        # 100 % : c'est la seule lecture qui ait un sens en cours d'exercice.
        repere = part_ecoulee if part_ecoulee is not None else 100.0
        if taux >= statique.SEUIL_LIGNE_DEPASSEE_PCT:
            statut = "depasse"
        elif taux >= statique.SEUIL_LIGNE_TENDUE_PCT or taux > repere + 15:
            statut = "tendu"
        else:
            statut = "normal"

        top_fournisseurs = sorted(l["fournisseurs"].items(), key=lambda kv: -kv[1])[:5]
        lignes.append({
            "ligne": l["ligne"],
            "budget_annuel_xof": budget,
            "consomme_xof": consomme,
            "reste_xof": budget - consomme,
            "consommation_pct": taux,
            "part_exercice_ecoulee_pct": part_ecoulee,
            "ecart_rythme_pts": round(taux - repere, 1),
            "nb_commandes": l["nb_commandes"],
            "nb_fournisseurs": len(l["fournisseurs"]),
            "statut": statut,
            "commentaire": l["commentaire"],
            "ligne_de_recueil": l["ligne"] == statique.LIGNE_RECUEIL,
            "motifs_utilises": sorted(l["motifs_utilises"]),
            "top_fournisseurs": [
                {"fournisseur": nom, "montant_xof": montant, "part_ligne_pct": pct(montant, consomme)}
                for nom, montant in top_fournisseurs
            ],
        })

    lignes.sort(key=lambda l: -l["consommation_pct"])
    budget_total = sum(l["budget_annuel_xof"] for l in lignes)
    consomme_total = sum(l["consomme_xof"] for l in lignes)
    recueil = next((l for l in lignes if l["ligne_de_recueil"]), None)

    return {
        # Budget posé + consommation mesurée : « mixte », jamais « statique ».
        "source": statique.SOURCE_MIXTE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "lignes": lignes,
        "totaux": {
            "budget_total_xof": budget_total,
            "consomme_total_xof": consomme_total,
            "reste_total_xof": budget_total - consomme_total,
            "consommation_pct": pct(consomme_total, budget_total),
            "part_exercice_ecoulee_pct": part_ecoulee,
            "nb_lignes_depassees": sum(1 for l in lignes if l["statut"] == "depasse"),
            "nb_lignes_tendues": sum(1 for l in lignes if l["statut"] == "tendu"),
            "nb_commandes_rattachees": sum(l["nb_commandes"] for l in lignes),
            "montant_non_rattache_xof": recueil["consomme_xof"] if recueil else 0,
            "part_non_rattachee_pct": pct(recueil["consomme_xof"] if recueil else 0, consomme_total),
        },
        "regle_mapping": statique.REGLE_BUDGET,
        "raison": statique.RAISON_BUDGET_STATIQUE,
        "avertissement": statique.AVERTISSEMENT_STATIQUE,
        "note": (
            "Le taux de consommation se lit contre la part d'exercice écoulée, jamais contre 100 % : "
            "c'est l'écart de rythme qui signale une dérive. La ligne de recueil n'est pas une ligne "
            "budgétaire réelle — ce qu'elle contient est à reclasser dans la grille."
        ),
    }


# ── Résultat net (projection) ───────────────────────────────────────────────

def build_resultat_net(marge_brute: dict, annee: int, aujourdhui: date) -> dict:
    """Projection de résultat net : marge mesurée, charges de structure posées, impôt posé.

    Trois champs distincts et un total nommé pour ce qu'il est. Le mot « projection »
    est repris jusque dans l'écran : un résultat net présenté comme mesuré serait
    cité en conseil d'administration.

    Les charges de structure sont proratisées sur les mois ÉCOULÉS de l'exercice,
    pas sur douze : comparer une marge à date à une année pleine de charges
    fabriquerait une perte qui n'existe pas.
    """
    mois_ecoules = 12 if aujourdhui.year > annee else (aujourdhui.month if aujourdhui.year == annee else 0)
    charges_mensuelles = sum(c["montant_mensuel_xof"] for c in statique.CHARGES_STRUCTURE_MENSUELLES)
    charges_periode = charges_mensuelles * mois_ecoules

    # La marge retenue est celle que la lecture de marge a elle-même retenue (par
    # dossier si l'imputation le permet, sur flux engagés sinon). Prendre la lecture
    # par dossier quand elle ne couvre que 0,5 % du CA aurait produit un résultat
    # net catastrophique et faux : des charges de huit mois contre la marge de deux
    # dossiers. La lecture utilisée est propagée jusqu'à l'écran.
    marge_xof = marge_brute["marge_retenue_xof"]
    resultat_avant_impot = marge_xof - charges_periode
    impot = round(resultat_avant_impot * statique.TAUX_IS_PCT / 100) if resultat_avant_impot > 0 else 0
    resultat_net = resultat_avant_impot - impot

    return {
        "source": statique.SOURCE_MIXTE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "mois_ecoules": mois_ecoules,
        "marge_brute_xof": marge_xof,
        "marge_brute_mesuree": True,
        "marge_brute_lecture": marge_brute["lecture_retenue"],
        "marge_brute_exploitable": marge_brute["couverture"]["exploitable"],
        "charges_structure_xof": charges_periode,
        "charges_structure_mensuelles_xof": charges_mensuelles,
        "resultat_avant_impot_xof": resultat_avant_impot,
        "taux_is_pct": statique.TAUX_IS_PCT,
        "impot_xof": impot,
        "resultat_net_projete_xof": resultat_net,
        "taux_resultat_net_pct": pct(resultat_net, marge_brute["ca_retenu_xof"]),
        "ca_reference_xof": marge_brute["ca_retenu_xof"],
        "charges_detail": [
            {
                "poste": c["poste"],
                "nature": c["nature"],
                "montant_mensuel_xof": c["montant_mensuel_xof"],
                "montant_periode_xof": c["montant_mensuel_xof"] * mois_ecoules,
                "part_pct": pct(c["montant_mensuel_xof"], charges_mensuelles),
            }
            for c in sorted(statique.CHARGES_STRUCTURE_MENSUELLES, key=lambda c: -c["montant_mensuel_xof"])
        ],
        "raison": statique.RAISON_RESULTAT_NET,
        "avertissement": statique.AVERTISSEMENT_STATIQUE,
        "note": (
            "Projection et non mesure : seule la marge brute est mesurée. Les charges de structure "
            "sont proratisées sur les mois écoulés de l'exercice, pas sur douze — sans quoi une marge "
            "à date se comparerait à une année pleine de charges. Aucun de ces montants ne remplace "
            "un compte de résultat. "
            + (
                "La marge utilisée est celle des dossiers imputés."
                if marge_brute["lecture_retenue"] == "dossiers"
                else "La marge utilisée est la marge sur flux engagés : l'imputation des dépenses de "
                     "dossier est trop faible sur cet exercice pour servir de base."
            )
        ),
    }


# ── Performance (indicateur global) ─────────────────────────────────────────

def build_performance(marge_brute: dict, socle_creances: dict, lignes_budget: dict,
                      annee: int, aujourdhui: date) -> dict:
    """Indice composite explicite : quatre composantes mesurées, quatre cibles posées.

    Le choix de fond : un indicateur « global » sans définition ne doit pas être
    inventé en silence. Chaque composante porte sa mesure, sa cible, son poids et
    son taux d'atteinte — l'indice est reconstituable à la main depuis l'écran, et
    donc contestable. Une composante non mesurable (marge non exploitable) n'est
    pas remplacée par une valeur neutre : elle est écartée et son poids est
    redistribué, ce que le retour signale.
    """
    cibles = statique.CIBLES_PERFORMANCE
    part_ecoulee = part_ecoulee_exercice_pct(annee, aujourdhui) or 100.0

    # La composante marge s'appuie sur la lecture retenue par `build_marge_brute` :
    # écarter la composante parce que l'imputation des dossiers est faible aurait
    # amputé l'indice de 35 % de son poids alors qu'une mesure complète existe.
    marge_pct = marge_brute["taux_retenu_pct"]
    dso = socle_creances["delai_encaissement_moyen_jours"]
    recouvrement = socle_creances["taux_recouvrement_pct"]
    consommation = lignes_budget["totaux"]["consommation_pct"]

    mesures = {
        "marge": {
            "valeur": marge_pct,
            "unite": "%",
            "cible": cibles["marge_brute_pct"],
            "sens": "haut",
            "mesure": (
                "CA définitif moins dépense définitive sur les dossiers imputés de l'exercice"
                if marge_brute["lecture_retenue"] == "dossiers"
                else "CA signé moins achats engagés de l'exercice (marge sur flux)"
            ),
            "source": statique.SOURCE_REELLE,
            "commentaire": (
                marge_brute["couverture"]["raison_non_exploitable"]
                or "Marge mesurée sur un périmètre de dépenses suffisamment imputé."
            ),
        },
        "recouvrement": {
            "valeur": recouvrement,
            "unite": "%",
            "cible": cibles["taux_recouvrement_pct"],
            "sens": "haut",
            "mesure": "montant réglé rapporté au montant réglé plus l'encours échu",
            "source": statique.SOURCE_REELLE,
            "commentaire": "L'encours non échu est exclu du dénominateur : il n'est pas en retard.",
        },
        "encours": {
            # Part de l'encours qui relève encore du recouvrement amiable. C'est le
            # signal que les trois autres composantes ne portent pas : un encours
            # majoritairement au-delà de 90 jours n'est plus un problème de délai,
            # c'est un problème de créances à provisionner.
            "valeur": round(100 - socle_creances["part_contentieux_pct"], 1),
            "unite": "%",
            "cible": cibles["part_encours_sain_pct"],
            "sens": "haut",
            "mesure": "part de l'encours client échu depuis moins de 90 jours",
            "source": statique.SOURCE_REELLE,
            "commentaire": (
                f"{socle_creances['nb_factures_contentieux']} factures dépassent 90 jours de retard, "
                f"soit {socle_creances['part_contentieux_pct']:.1f} % de l'encours."
            ),
        },
        "dso": {
            "valeur": dso,
            "unite": "jours",
            "cible": float(cibles["dso_jours"]),
            "sens": "bas",
            "mesure": "délai moyen facture → règlement, sur les factures effectivement réglées",
            "source": statique.SOURCE_REELLE,
            "commentaire": (
                "Lecture comportementale. La lecture bilancielle (encours rapporté au CA) ressort à "
                f"{socle_creances['dso_encours_jours']} jours et mesure le stock d'impayés."
                if socle_creances["dso_encours_jours"] is not None
                else "Lecture comportementale, sur les factures réglées."
            ),
        },
        "budget": {
            # Tenue du budget : consommer moins que la part d'exercice écoulée vaut
            # 100 %. La cible n'est donc pas 100 % de consommation mais le RYTHME.
            "valeur": consommation,
            "unite": "%",
            "cible": round(part_ecoulee, 1),
            "sens": "bas",
            "mesure": "achats engagés rattachés aux lignes budgétaires, rapportés au budget posé",
            "source": statique.SOURCE_MIXTE,
            "commentaire": (
                "Le budget de référence est posé (aucune table budgétaire n'existe) : cette "
                "composante mesure un rythme de dépense, pas le respect d'un budget voté."
            ),
        },
    }

    composantes, indice, poids_retenu = [], 0.0, 0
    for poids in statique.POIDS_PERFORMANCE:
        m = mesures[poids["code"]]
        atteinte = taux_atteinte_pct(m["valeur"], m["cible"], m["sens"])
        composantes.append({
            "code": poids["code"],
            "libelle": poids["libelle"],
            "poids_pct": poids["poids_pct"],
            "valeur": m["valeur"],
            "unite": m["unite"],
            "cible": m["cible"],
            "sens": m["sens"],
            "taux_atteinte_pct": atteinte,
            "retenue": atteinte is not None,
            "source": m["source"],
            "mesure": m["mesure"],
            "commentaire": m["commentaire"],
        })
        if atteinte is not None:
            indice += atteinte * poids["poids_pct"]
            poids_retenu += poids["poids_pct"]

    indice_pct = round(indice / poids_retenu, 1) if poids_retenu else None
    if indice_pct is None:
        verdict = "non calculable"
    elif indice_pct >= 100:
        verdict = "au-dessus des cibles"
    elif indice_pct >= 85:
        verdict = "conforme"
    elif indice_pct >= 70:
        verdict = "sous tension"
    else:
        verdict = "critique"

    ecartees = [c["libelle"] for c in composantes if not c["retenue"]]
    return {
        # Composantes mesurées, cibles posées : mixte.
        "source": statique.SOURCE_MIXTE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "indice_pct": indice_pct,
        "verdict": verdict,
        "composantes": composantes,
        "poids_retenu_pct": poids_retenu,
        "composantes_ecartees": ecartees,
        "regle": statique.REGLE_PERFORMANCE,
        "avertissement": statique.AVERTISSEMENT_STATIQUE if ecartees else None,
        "note": (
            "Indice reconstituable à la main : chaque composante affiche sa mesure, sa cible, son "
            "poids et son taux d'atteinte, borné à 120 % pour qu'une composante exceptionnelle ne "
            "compense pas l'effondrement des autres. "
            + (
                f"Composante(s) écartée(s) faute de mesure exploitable : {', '.join(ecartees)} — le "
                f"poids restant a été renormalisé sur {poids_retenu} %."
                if ecartees
                else "Les quatre composantes sont mesurées."
            )
        ),
    }
