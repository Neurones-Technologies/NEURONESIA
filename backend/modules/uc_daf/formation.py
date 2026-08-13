"""Volet transverse — Formation des utilisateurs et qualité de la saisie.

Demande du DAF : « Formation des utilisateurs aux bons usages de l'outil, afin
d'éviter tout impact négatif (erreur de saisie, corruption) sur les données. »

Le choix de fond de cet écran : une formation ne se pilote pas sur des intentions.
Le contenu pédagogique est posé (aucun référentiel de formation n'existe dans le
système), mais chaque module est rattaché à un CONTRÔLE MESURÉ sur les données
réelles. Trois conséquences :

- la formation est priorisée par ce qui est effectivement mal saisi, pas par ce
  qu'on imagine mal saisi. Sur ce miroir, cela remonte d'abord le référentiel
  client (1 507 fiches sans secteur sur 1 508) et l'imputation des dépenses de
  dossier (1 424 dossiers sans dépense définitive sur 2 408) ;
- chaque défaut est relié à l'INDICATEUR qu'il casse. « Le secteur n'est pas
  renseigné » n'engage personne ; « aucune lecture sectorielle du risque client
  n'est possible » engage ;
- l'effet de la formation est vérifiable après coup : les mêmes compteurs, relus
  un mois plus tard, disent si la saisie s'est améliorée.

Un contrôle mérite une précision : l'absence de facture fournisseur n'est pas une
erreur de saisie mais un défaut de RACCORDEMENT (la synchronisation des
`in_invoice` n'existe pas). Il figure quand même ici, marqué comme structurel,
parce que c'est le premier trou de données du volet financier et que la formation
des équipes achats en dépend.
"""
from __future__ import annotations

from datetime import date

from modules.uc_daf import statique
from modules.uc_daf.commun import pct

# Métadonnées des contrôles : ce que chaque défaut casse, et comment on le corrige.
# Ce ne sont pas des données posées mais la lecture métier des compteurs mesurés —
# d'où leur place ici et non dans `statique.py`.
CONTROLES = {
    "echeance_incoherente": {
        "libelle": "Factures sans échéance ou d'échéance antérieure à la facture",
        "objet": "invoices.due_date",
        "indicateur_casse": "Trésorerie prévisionnelle, balance âgée, vigilance avant échéance",
        "correction": "Corriger l'échéance dans Odoo d'après le délai contractuel du client.",
        "structurel": False,
    },
    "reglement_non_rattache": {
        "libelle": "Factures soldées sans date de règlement rattachée",
        "objet": "invoices.payment_date",
        "indicateur_casse": "DSO réel, comportement de paiement, prévision d'encaissement",
        "correction": "Rattacher le règlement à la facture qu'il solde, pas au compte client.",
        "structurel": False,
    },
    "facture_fournisseur_absente": {
        "libelle": "Achats engagés sans facture fournisseur dans le système",
        "objet": "supplier_invoices (table vide)",
        "indicateur_casse": "DPO, dette échue, échéancier de décaissement",
        "correction": "Raccorder la synchronisation des factures fournisseurs (in_invoice), puis "
                      "saisir les échéances et les règlements comme côté client.",
        "structurel": True,
    },
    "achat_sans_dossier": {
        "libelle": "Commandes d'achat non rattachées à un dossier",
        "objet": "purchase_orders.dossier_id",
        "indicateur_casse": "Marge par dossier, marge de sous-traitance, imputation des charges",
        "correction": "Renseigner le dossier à la création de la commande d'achat.",
        "structurel": False,
    },
    "dossier_sans_depense": {
        "libelle": "Dossiers sans dépense définitive imputée",
        "objet": "dossiers.depense_definitive",
        "indicateur_casse": "Marge brute réalisée à date, résultat net projeté, indice de performance",
        "correction": "Imputer la dépense définitive à la clôture du dossier, même si une facture "
                      "fournisseur reste attendue.",
        "structurel": False,
    },
    "client_sans_secteur": {
        "libelle": "Clients sans secteur d'activité renseigné",
        "objet": "clients.sector",
        "indicateur_casse": "Lecture sectorielle du risque client et de la concentration",
        "correction": "Renseigner le secteur depuis la nomenclature validée, jamais en texte libre.",
        "structurel": False,
    },
    "document_en_devise": {
        "libelle": "Documents libellés en devise étrangère (taux non conservé)",
        "objet": "purchase_orders.currency, invoices.currency",
        "indicateur_casse": "Top des charges, cumuls d'achats, écarts de change",
        "correction": "Conserver le taux appliqué à la date d'engagement ; comptabiliser l'écart de "
                      "change au règlement.",
        "structurel": True,
    },
    "facture_sans_client": {
        "libelle": "Factures dont le client n'existe pas dans le référentiel",
        "objet": "invoices.client_id",
        "indicateur_casse": "Suivi des mauvais payeurs, encours par client, relances",
        "correction": "Rétablir la fiche client ou rattacher la facture au bon tiers.",
        "structurel": False,
    },
}

# Seuils de gravité sur la part de lignes en défaut. Un contrôle structurel est
# critique quel que soit son taux : ce n'est pas une négligence de saisie, c'est un
# trou de données qui rend l'indicateur impossible.
SEUIL_CRITIQUE_PCT = 40.0
SEUIL_ATTENTION_PCT = 10.0


def _gravite(part_defaut_pct: float, structurel: bool) -> str:
    if structurel:
        return "critique"
    if part_defaut_pct >= SEUIL_CRITIQUE_PCT:
        return "critique"
    if part_defaut_pct >= SEUIL_ATTENTION_PCT:
        return "attention"
    return "info"


def build_formation(controles_mesures: dict[str, dict], aujourdhui: date) -> dict:
    """Modules de formation priorisés par la qualité de saisie réellement mesurée.

    L'ordre des modules n'est pas celui de la note du DAF : c'est celui des défauts
    constatés, gravité puis taux décroissants. Une formation qui commence par le
    sujet le mieux tenu perd la salle.
    """
    controles = []
    for code, meta in CONTROLES.items():
        mesure = controles_mesures.get(code, {})
        nb_defaut = int(mesure.get("nb_defaut", 0))
        nb_total = int(mesure.get("nb_total", 0))
        part = pct(nb_defaut, nb_total)
        controles.append({
            "code": code,
            "libelle": meta["libelle"],
            "objet": meta["objet"],
            "nb_defaut": nb_defaut,
            "nb_total": nb_total,
            "part_defaut_pct": part,
            "part_conforme_pct": round(100 - part, 1),
            "gravite": _gravite(part, meta["structurel"]),
            "structurel": meta["structurel"],
            "indicateur_casse": meta["indicateur_casse"],
            "correction": meta["correction"],
        })

    ordre_gravite = {"critique": 0, "attention": 1, "info": 2}
    controles.sort(key=lambda c: (ordre_gravite[c["gravite"]], -c["part_defaut_pct"]))

    # Score de qualité : moyenne simple des taux de conformité, volontairement non
    # pondérée. Une pondération inventée donnerait un score plus flatteur ou plus
    # sévère sans qu'on puisse la justifier ; la moyenne simple se recalcule depuis
    # les huit lignes affichées.
    conformites = [c["part_conforme_pct"] for c in controles]
    score = round(sum(conformites) / len(conformites), 1) if conformites else None

    par_code = {c["code"]: c for c in controles}
    modules = []
    for m in statique.MODULES_FORMATION:
        controle = par_code.get(m["code_controle"])
        modules.append({
            "code": m["code"],
            "titre": m["titre"],
            "public": m["public"],
            "duree_min": m["duree_min"],
            "objectif": m["objectif"],
            "points": m["points"],
            "risque_si_absent": m["risque_si_absent"],
            "controle": controle,
            "priorite": (
                ordre_gravite[controle["gravite"]] if controle else 3,
                -(controle["part_defaut_pct"] if controle else 0),
            ),
        })
    modules.sort(key=lambda m: m["priorite"])
    for rang, m in enumerate(modules, start=1):
        m["rang"] = rang
        del m["priorite"]

    return {
        # Contenu pédagogique posé, compteurs de défaut mesurés.
        "source": statique.SOURCE_MIXTE,
        "as_of": aujourdhui.isoformat(),
        "modules": modules,
        "controles": controles,
        "qualite": {
            "score_global_pct": score,
            "nb_controles": len(controles),
            "nb_critiques": sum(1 for c in controles if c["gravite"] == "critique"),
            "nb_attention": sum(1 for c in controles if c["gravite"] == "attention"),
            "nb_structurels": sum(1 for c in controles if c["structurel"]),
            "methode": "Moyenne simple des taux de conformité des huit contrôles, chacun mesuré sur "
                       "son assiette réelle. Non pondérée, pour rester recalculable depuis l'écran.",
            "seuils": {"critique_pct": SEUIL_CRITIQUE_PCT, "attention_pct": SEUIL_ATTENTION_PCT},
        },
        "regles_or": statique.REGLES_OR,
        "duree_totale_min": sum(m["duree_min"] for m in modules),
        "note": statique.NOTE_FORMATION,
    }
