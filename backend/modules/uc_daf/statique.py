"""TOUT ce qui est posé faute de donnée réelle côté DAF — un seul fichier, exprès.

Mêmes quatre règles que `uc_commercial/statique.py`, reprises sans exception :

1. UN SEUL FICHIER. Quand la donnée arrive (comptabilité générale raccordée,
   factures fournisseurs synchronisées, budget saisi), ce qu'il faut supprimer se
   trouve ici et nulle part ailleurs.
2. TOUT PORTE `source: "statique"`, et le front l'affiche.
3. AUCUN MÉLANGE DANS UNE MÊME VALEUR. Le résultat net combine une marge brute
   MESURÉE et des charges de structure POSÉES : les deux restent deux champs, le
   total est nommé « projection » et le bloc porte `source: "mixte"`.
4. AUCUN NOM DE PERSONNE INVENTÉ. Les postes de charge portent des fonctions et
   des natures comptables, jamais un nom fabriqué.

Les noms de FOURNISSEURS et de CLIENTS qui apparaissent dans les écrans DAF ne
sont, eux, jamais posés ici : ils viennent du miroir. Ce fichier ne contient que
des décisions (budget, cibles, délais négociés) et du contenu pédagogique.
"""
from __future__ import annotations

# Marqueurs de provenance — contrat partagé avec le front (`SourceDonnees` dans
# lib/api/commercial.ts). Ne pas reformuler ces valeurs : elles sont testées.
SOURCE_STATIQUE = "statique"
SOURCE_REELLE = "reel"
SOURCE_MIXTE = "mixte"

AVERTISSEMENT_STATIQUE = (
    "Données de démonstration : la donnée réelle n'existe pas encore dans le système. "
    "La forme de l'indicateur est définitive, les valeurs ne le sont pas."
)


# ── Tableau de bord n°1 — Charges de structure et résultat net ───────────────
#
# Aucune comptabilité générale n'est raccordée au système : le miroir Odoo
# synchronisé ne porte que des factures clients, des commandes (ventes et achats)
# et des dossiers. Masse salariale, loyers, énergie, amortissements, frais
# financiers et impôts sont donc HORS du périmètre mesurable — et sans eux, un
# résultat net est impossible à calculer, pas seulement imprécis.
#
# Le gabarit ci-dessous pose un plan de charges mensuel d'ordre de grandeur pour
# une ESN de la taille de Neurones Technologies. Il sert à deux choses : montrer
# la forme de l'indicateur, et donner au DAF une NOMENCLATURE DE POSTES à valider
# — c'est elle qui déterminera le raccordement comptable à mener.
#
# `nature` distingue ce qui tombe tous les mois de ce qui suit l'activité : un
# résultat net projeté sur des charges toutes fixes serait faux dans l'autre sens.
CHARGES_STRUCTURE_MENSUELLES = [
    {"poste": "Masse salariale et charges sociales", "montant_mensuel_xof": 178_000_000, "nature": "fixe"},
    {"poste": "Sous-traitance technique récurrente", "montant_mensuel_xof": 42_000_000, "nature": "variable"},
    {"poste": "Loyers et charges locatives", "montant_mensuel_xof": 21_500_000, "nature": "fixe"},
    {"poste": "Télécoms, connectivité et hébergement interne", "montant_mensuel_xof": 14_800_000, "nature": "fixe"},
    {"poste": "Énergie et groupe électrogène", "montant_mensuel_xof": 9_600_000, "nature": "variable"},
    {"poste": "Déplacements et frais de mission", "montant_mensuel_xof": 8_400_000, "nature": "variable"},
    {"poste": "Honoraires (conseil, audit, juridique)", "montant_mensuel_xof": 6_200_000, "nature": "fixe"},
    {"poste": "Assurances", "montant_mensuel_xof": 4_100_000, "nature": "fixe"},
    {"poste": "Amortissements", "montant_mensuel_xof": 12_700_000, "nature": "fixe"},
    {"poste": "Frais bancaires et charges financières", "montant_mensuel_xof": 5_300_000, "nature": "variable"},
    {"poste": "Impôts et taxes hors IS", "montant_mensuel_xof": 7_900_000, "nature": "fixe"},
]

RAISON_CHARGES_STRUCTURE = (
    "Aucune comptabilité générale n'est raccordée : le miroir ne synchronise que les factures "
    "clients, les commandes et les dossiers. Masse salariale, loyers, amortissements et impôts "
    "n'existent nulle part dans le système — c'est un raccordement à faire, pas une saisie à "
    "améliorer. La nomenclature de postes ci-dessus est une proposition à valider par le DAF."
)

# Taux d'impôt sur les sociétés retenu pour la projection (Côte d'Ivoire, régime
# de droit commun). Posé, pas mesuré : aucune liasse fiscale n'est raccordée.
TAUX_IS_PCT = 25.0

RAISON_RESULTAT_NET = (
    "Le résultat net n'est pas mesurable : il suppose des charges de structure, des "
    "amortissements et un impôt qui ne figurent dans aucune table du système. Le montant affiché "
    "est une PROJECTION — marge brute mesurée moins charges de structure posées, moins impôt au "
    f"taux de {TAUX_IS_PCT:.0f} %. Aucune de ces trois composantes n'a été validée en comptabilité."
)


# ── Tableau de bord n°1 — Budget voté et lignes budgétaires ──────────────────
#
# Aucune table budgétaire n'existe dans le système, et aucun fait du miroir ne
# permet d'inférer un budget : un budget est une DÉCISION votée.
#
# Le gabarit ne se contente pas de poser des montants : il pose une GRILLE DE
# RATTACHEMENT (motifs sur le nom du fournisseur) qui rend la CONSOMMATION
# mesurable sur les achats réels. Chaque ligne budgétaire a donc un budget posé et
# un consommé mesuré — d'où `source: "mixte"` sur ce bloc, jamais "statique".
#
# Même mécanique que la grille d'axes stratégiques du DC
# (`uc_commercial.marche.AXES_DEFAUT`) : les motifs se lisent sur un libellé
# normalisé (minuscules, sans accent), le premier motif qui matche gagne selon
# `priority`, et une ligne « Non rattaché » recueille le reste — jamais de
# rattachement silencieux par défaut.
BUDGET_LIGNES = [
    {
        "ligne": "Matériel et infrastructure",
        "budget_annuel_xof": 4_200_000_000,
        # Les grossistes sont nommés un par un, comme les éditeurs de la grille
        # d'axes du DC : aucun champ de catégorie n'existe sur `purchase_orders`, le
        # nom du fournisseur est la seule prise. Cette liste a été complétée en
        # regardant les plus gros non-rattachés de l'exercice (Exclusive Networks,
        # Network Distributors, Trinexia, Mindware…), et le montant qui reste dans la
        # ligne de recueil est affiché pour que le DAF puisse continuer l'arbitrage.
        "motifs": ["polaris", "hiperdist", "westcon", "mitsumi", "hdf", "aitek", "ndc pro",
                   "tech data", "ingram", "logicom", "redington", "exclusive network",
                   "exclusiv network", "network distributor", "ndist", "mindware", "fvc mea",
                   "trinexia", "cyber knight", "four nordic"],
        "priority": 10,
        "commentaire": "Distributeurs et grossistes matériel — poste le plus lourd, revendu au client.",
    },
    {
        "ligne": "Licences et abonnements éditeurs",
        "budget_annuel_xof": 1_600_000_000,
        "motifs": ["microsoft", "csp", "oracle", "vmware", "adobe", "autodesk", "sap",
                   "veeam", "fortinet", "kaspersky", "trend micro", "wallix", "darktrace"],
        "priority": 20,
        "commentaire": "Licences revendues et abonnements internes — à séparer une fois le CSP isolé.",
    },
    {
        "ligne": "Prestations et sous-traitance",
        "budget_annuel_xof": 900_000_000,
        "motifs": ["consult", "service", "sarl", "expertise", "ingenierie", "bureau", "training"],
        "priority": 30,
        "commentaire": "Sous-traitance technique et prestations intellectuelles.",
    },
    {
        "ligne": "Logistique, transport et douane",
        "budget_annuel_xof": 420_000_000,
        "motifs": ["logistique", "transit", "transport", "douane", "dhl", "fedex", "mc3", "bolloré", "bollore"],
        "priority": 40,
        "commentaire": "Acheminement et dédouanement du matériel importé.",
    },
    {
        "ligne": "Télécoms et connectivité",
        "budget_annuel_xof": 260_000_000,
        "motifs": ["orange", "mtn", "moov", "telecom", "vitib", "arobase"],
        "priority": 50,
        "commentaire": "Liens, hébergement et connectivité — internes comme refacturés.",
    },
    {
        "ligne": "Frais généraux et divers achats",
        "budget_annuel_xof": 340_000_000,
        "motifs": [],
        "priority": 900,
        "commentaire": "Ligne de recueil : tout achat qu'aucun motif ci-dessus ne rattache.",
    },
]

# Nom de la ligne de recueil. Isolé en constante : le calcul en a besoin pour ne
# jamais compter un achat deux fois, et l'écran pour dire au DAF ce qu'il devrait
# reclasser plutôt que de laisser croire à une ligne budgétaire réelle.
LIGNE_RECUEIL = "Frais généraux et divers achats"

REGLE_BUDGET = (
    "Budget annuel POSÉ par ligne (aucune table budgétaire n'existe dans le système), "
    "consommation MESURÉE sur les commandes d'achat réelles rattachées par motif sur le nom du "
    "fournisseur. Le budget doit être remplacé par le budget voté ; la grille de rattachement, "
    "elle, est éditable et c'est au DAF de l'arbitrer."
)

RAISON_BUDGET_STATIQUE = (
    "Aucune table budgétaire n'existe dans le système : ni budget voté, ni ligne, ni engagement. "
    "Un budget est une décision, pas une donnée synchronisée — il devra être saisi ou importé."
)

# Seuils de lecture d'une ligne budgétaire. Posés, mais discutables à l'écran :
# une consommation à 95 % au mois de mars n'a pas le même sens qu'en décembre,
# c'est pourquoi le calcul les compare TOUJOURS à la part d'exercice écoulée.
SEUIL_LIGNE_TENDUE_PCT = 85.0
SEUIL_LIGNE_DEPASSEE_PCT = 100.0


# ── Tableau de bord n°1 — Performance (indicateur global) ────────────────────
#
# « Performance » est demandé comme indicateur GLOBAL, sans définition. Faute de
# définition, l'indicateur n'est pas inventé en silence : il est composé de quatre
# composantes MESURÉES, chacune comparée à une CIBLE posée ici, avec ses poids
# affichés à l'écran. Le DAF peut donc contester la pondération et les cibles —
# c'est l'intérêt d'un composite explicite face à un score opaque.
CIBLES_PERFORMANCE = {
    "marge_brute_pct": 35.0,
    "dso_jours": 60,
    "taux_recouvrement_pct": 90.0,
    "consommation_budget_pct": 100.0,
    # Part de l'encours client échu depuis moins de 90 jours. Cette composante a été
    # ajoutée après avoir vu l'indice : sans elle, l'indice ressortait « au-dessus
    # des cibles » alors que 85 % de l'encours client dépasse 90 jours de retard.
    # Un indicateur global qui ne voit pas le premier problème financier de
    # l'entreprise n'a aucune valeur.
    "part_encours_sain_pct": 85.0,
}

POIDS_PERFORMANCE = [
    {"code": "marge", "libelle": "Marge brute réalisée", "poids_pct": 30},
    {"code": "recouvrement", "libelle": "Recouvrement des créances", "poids_pct": 25},
    {"code": "encours", "libelle": "Qualité de l'encours client", "poids_pct": 20},
    {"code": "dso", "libelle": "Délai d'encaissement (DSO)", "poids_pct": 15},
    {"code": "budget", "libelle": "Tenue du budget", "poids_pct": 10},
]

REGLE_PERFORMANCE = (
    "Indice composite : chaque composante est mesurée puis rapportée à une cible posée "
    "(marge brute 35 %, recouvrement 90 %, encours à moins de 90 jours 85 %, DSO 60 jours, "
    "consommation budgétaire à hauteur de l'exercice écoulé), et les cinq taux d'atteinte sont "
    "pondérés (30/25/20/15/10). Les cibles et les poids sont des hypothèses de travail, pas des "
    "objectifs validés — c'est précisément ce que le DAF doit arbitrer sur cet écran."
)


# ── Tableau de bord n°2 — DPO (dettes fournisseurs) ─────────────────────────
#
# `supplier_invoices` est VIDE : aucune facture fournisseur n'est synchronisée
# (seules les factures clients, `out_invoice`, le sont — cf. le commentaire de
# `SupplierInvoiceModel`). Sans facture fournisseur, il n'y a ni échéance, ni date
# de règlement, ni reste dû : le DPO n'est pas approchable, il est INCALCULABLE.
#
# Ce que le miroir porte quand même, et qui est mesuré côté module : les achats
# ENGAGÉS (2 133 commandes) et, pour deux fournisseurs seulement, un délai de
# paiement négocié (`suppliers.payment_term_days`). Un engagement n'est pas une
# dette : une commande passée n'est pas encore une facture reçue.
#
# Dès que la synchronisation des factures fournisseurs sera en place, le module
# calcule le DPO réel et ce gabarit cesse d'être servi (cf. `build_dpo`).
DPO_STATIQUE_JOURS = 74
DELAI_NEGOCIE_MOYEN_JOURS = 45

# Échéancier de dette posé, en part du total dû — sert la forme de la balance âgée
# fournisseurs, que l'écran affiche à côté de la balance âgée clients (mesurée).
DPO_TRANCHES_STATIQUES = [
    {"code": "non_echu", "libelle": "Non échu", "part_pct": 41.0},
    {"code": "0_30", "libelle": "Échu de 1 à 30 jours", "part_pct": 27.0},
    {"code": "31_60", "libelle": "Échu de 31 à 60 jours", "part_pct": 18.0},
    {"code": "61_90", "libelle": "Échu de 61 à 90 jours", "part_pct": 9.0},
    {"code": "90_plus", "libelle": "Échu depuis plus de 90 jours", "part_pct": 5.0},
]

RAISON_DPO_STATIQUE = (
    "La table des factures fournisseurs est vide : seules les factures clients sont "
    "synchronisées depuis l'ERP. Sans facture fournisseur, il n'existe ni échéance, ni date de "
    "règlement, ni reste dû — le DPO n'est pas approximable, il est incalculable. Ce qui est "
    "mesuré ici, ce sont les achats ENGAGÉS (commandes), qui ne sont pas encore une dette."
)


# ── Tableau de bord n°3 — Trésorerie prévisionnelle ─────────────────────────
#
# Vigilance : nombre de jours avant échéance au-delà duquel une créance n'est pas
# encore « proche ». 30 jours par défaut — le DAF a demandé une alerte AVANT
# échéance, pas un constat de retard.
HORIZON_VIGILANCE_JOURS = 30

# Horizon de l'atterrissage calendaire, en mois glissants à partir du mois courant.
HORIZON_ATTERRISSAGE_MOIS = 6

# Nombre de mois d'historique servant de base à la projection de décaissement.
# Mesuré sur les achats réels, projeté par moyenne — l'hypothèse est affichée.
FENETRE_RUN_RATE_MOIS = 6

RAISON_DECAISSEMENT_PROJETE = (
    "Les décaissements prévisionnels ne peuvent pas être échéancés : sans facture fournisseur "
    "synchronisée, aucune date de règlement n'existe. La projection retenue est la moyenne "
    "mensuelle des achats réellement engagés sur les six derniers mois, reportée sur les mois à "
    "venir. C'est un ordre de grandeur mesuré sur du réel, pas un échéancier."
)

METHODE_ENCAISSEMENT = (
    "Encaissements prévisionnels : chaque créance ouverte est positionnée à son échéance réelle, "
    "décalée du retard moyen CONSTATÉ sur les factures déjà réglées de ce même client (retard "
    "global observé quand le client a moins de trois factures réglées). L'échéancier est mesuré, "
    "le décalage est un comportement observé — pas une promesse du client."
)

# Seuil de découvert à signaler sur le calendrier d'atterrissage. Posé : aucun
# plafond de découvert bancaire n'est renseigné dans le système.
SEUIL_ALERTE_SOLDE_XOF = -500_000_000
