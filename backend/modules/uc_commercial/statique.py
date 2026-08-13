"""TOUT ce qui est encore figé faute de donnée réelle — un seul fichier, exprès.

Le compte-rendu DC du 04/08/2026 demande des indicateurs dont la donnée n'existe
pas dans le miroir. Plutôt que de laisser ces écrans vides, ils sont servis avec
un GABARIT : la forme définitive de l'indicateur, alimentée par des valeurs
posées à la main.

Quatre règles, sans exception :

1. UN SEUL FICHIER. Quand la donnée arrive, ce qu'il faut supprimer se trouve ici
   et nulle part ailleurs. Aucune valeur figée ne doit être écrite dans un module
   de calcul ni dans un composant d'écran.
2. TOUT PORTE `source: "statique"`. Chaque bloc renvoyé au front est marqué, et
   le front l'affiche. Un chiffre de démonstration présenté comme mesuré finit
   dans une revue de performance et fait prendre une mauvaise décision.
3. AUCUN MÉLANGE DANS UNE MÊME VALEUR. Un montant ne se compose jamais d'une
   part mesurée et d'une part inventée. Quand les deux coexistent sur un écran
   (le Gap : objectif figé, réalisé mesuré), ils restent deux champs distincts et
   le retour porte `source: "mixte"`.
4. AUCUN NOM DE PERSONNE INVENTÉ. Les gabarits qui exigent un interlocuteur
   portent une FONCTION (« DSI », « Responsable infrastructure »), jamais un nom
   fabriqué : un faux compte-rendu attribué à une personne nommée est une pièce
   qui peut circuler hors de son contexte.

Les noms de COMPTES, eux, sont réels : ce sont les clients du DC, la forme n'est
lisible qu'avec eux, et le tag « exemple » reste porté par chaque ligne.
"""
from __future__ import annotations

# Marqueur unique, repris à l'identique par tous les endpoints qui servent un
# gabarit. Le front le teste sur cette valeur : ne pas la reformuler.
SOURCE_STATIQUE = "statique"
SOURCE_REELLE = "reel"
SOURCE_MIXTE = "mixte"

AVERTISSEMENT_STATIQUE = (
    "Données de démonstration : la donnée réelle n'existe pas encore dans le système. "
    "La forme de l'indicateur est définitive, les valeurs ne le sont pas."
)


# ── §3 du CR — Objectifs commerciaux ────────────────────────────────────────
#
# Aucun objectif n'existe en base (`commercial_objectives` est vide) et aucun fait
# du miroir ne permet de l'inférer : un objectif est une DÉCISION.
#
# Le gabarit ne pose donc pas un montant en dur — un montant arbitraire aurait
# l'air d'un objectif validé. Il pose une RÈGLE lisible et discutable : « CA de
# l'année précédente + 10 % », déclinée par commercial au prorata de son réalisé.
# Le DC valide ou remplace la règle ; l'écran, lui, existe déjà.
COEFF_OBJECTIF_DEMO = 1.10

REGLE_OBJECTIF_DEMO = (
    "Objectif provisoire = CA signé de l'année précédente + 10 %, réparti entre les commerciaux "
    "au prorata de leur réalisé N-1 et entre les trimestres selon la saisonnalité observée. "
    "Aucune de ces trois hypothèses n'a été validée par la Direction Commerciale."
)

# Répartition trimestrielle du gabarit. Volontairement PAS 25/25/25/25 : un
# objectif linéaire ferait passer un T1 normalement creux pour un retard.
SAISONNALITE_TRIMESTRES = {1: 0.20, 2: 0.25, 3: 0.22, 4: 0.33}

# §2/§3 du CR — « 30 millions ». Le cadrage relève que le chiffre est employé à
# deux endroits avec deux sens (seuil de traçage, objectif de vente). Retenu ici
# comme SEUIL de traçage du cycle de vie, en FCFA — l'usage le moins ambigu des
# deux. La question « FCFA ou euros » reste ouverte côté DC.
SEUIL_CYCLE_VIE_XOF = 30_000_000

# §3 du CR — volume de leads annuel à générer, illisible sur la note manuscrite.
OBJECTIF_LEADS_ANNUEL = 900


# ── §3 du CR — Indice de prospection ────────────────────────────────────────
#
# `opportunities.created_at` est renseigné à 100 % mais inexploitable : 4 927 des
# 9 475 opportunités portent la date du 07/04/2026 et 1 548 celle du 02/07/2026 —
# ce sont les dates d'import, pas de création. Compter les opportunités générées
# par mois sur cette colonne produirait deux pics d'import et dix mois à zéro.
#
# Aucune table de leads n'existe par ailleurs : seules les opportunités remontent
# de l'ERP.
PROSPECTION_MENSUELLE_STATIQUE = [
    {"mois": 1, "nb_opportunites": 58, "nb_nouveaux_comptes": 4, "montant_genere_xof": 1_240_000_000},
    {"mois": 2, "nb_opportunites": 64, "nb_nouveaux_comptes": 6, "montant_genere_xof": 1_410_000_000},
    {"mois": 3, "nb_opportunites": 71, "nb_nouveaux_comptes": 5, "montant_genere_xof": 1_680_000_000},
    {"mois": 4, "nb_opportunites": 52, "nb_nouveaux_comptes": 3, "montant_genere_xof": 980_000_000},
    {"mois": 5, "nb_opportunites": 69, "nb_nouveaux_comptes": 7, "montant_genere_xof": 1_520_000_000},
    {"mois": 6, "nb_opportunites": 77, "nb_nouveaux_comptes": 6, "montant_genere_xof": 1_890_000_000},
    {"mois": 7, "nb_opportunites": 45, "nb_nouveaux_comptes": 2, "montant_genere_xof": 860_000_000},
    {"mois": 8, "nb_opportunites": 38, "nb_nouveaux_comptes": 2, "montant_genere_xof": 720_000_000},
    {"mois": 9, "nb_opportunites": 66, "nb_nouveaux_comptes": 5, "montant_genere_xof": 1_450_000_000},
    {"mois": 10, "nb_opportunites": 73, "nb_nouveaux_comptes": 6, "montant_genere_xof": 1_720_000_000},
    {"mois": 11, "nb_opportunites": 81, "nb_nouveaux_comptes": 8, "montant_genere_xof": 2_050_000_000},
    {"mois": 12, "nb_opportunites": 62, "nb_nouveaux_comptes": 4, "montant_genere_xof": 1_310_000_000},
]

RAISON_PROSPECTION_STATIQUE = (
    "Les dates de création des opportunités du miroir sont des dates d'import (4 927 opportunités "
    "au 07/04/2026, 1 548 au 02/07/2026) : elles ne permettent pas de compter ce qui a été généré "
    "mois par mois. Aucune table de leads n'existe non plus — seules les opportunités remontent de l'ERP."
)


# ── §1/§4 du CR — Analyse sectorielle et part de marché ─────────────────────
#
# `clients.sector` est renseigné pour 1 client sur 1 508. Le gabarit ci-dessous
# sert deux buts : montrer la forme de l'écran, et donner au DC une NOMENCLATURE
# à valider ou corriger — c'est la question 35 du cadrage (« une dizaine de
# grandes catégories, ou plus fin ? »).
#
# `taille_marche_xof` est le point le plus délicat : sans source externe, une
# part de marché est incalculable. Les valeurs ci-dessous sont des ordres de
# grandeur de travail, à remplacer par une étude ou des données publiques.
SECTEURS_STATIQUES = [
    {"secteur": "Banque et assurance", "ca_xof": 3_850_000_000, "nb_clients": 34,
     "croissance_pct": 8.4, "taille_marche_xof": 62_000_000_000},
    {"secteur": "Télécommunications", "ca_xof": 3_120_000_000, "nb_clients": 11,
     "croissance_pct": -3.2, "taille_marche_xof": 48_000_000_000},
    {"secteur": "Secteur public et administrations", "ca_xof": 2_240_000_000, "nb_clients": 47,
     "croissance_pct": 14.1, "taille_marche_xof": 71_000_000_000},
    {"secteur": "Industrie, mines et énergie", "ca_xof": 1_480_000_000, "nb_clients": 28,
     "croissance_pct": 5.7, "taille_marche_xof": 39_000_000_000},
    {"secteur": "Distribution et services", "ca_xof": 1_180_000_000, "nb_clients": 52,
     "croissance_pct": 2.1, "taille_marche_xof": 27_000_000_000},
    {"secteur": "Institutions et bailleurs", "ca_xof": 940_000_000, "nb_clients": 19,
     "croissance_pct": 11.8, "taille_marche_xof": 22_000_000_000},
]

RAISON_SECTEUR_STATIQUE = (
    "Le secteur d'activité n'est renseigné que pour 1 client sur 1 508 dans le référentiel. "
    "La nomenclature ci-dessus est une proposition à valider : c'est elle qui déterminera la "
    "saisie à mener, pas l'inverse."
)

RAISON_PART_MARCHE_STATIQUE = (
    "Aucune source externe de taille de marché n'est raccordée au système. Sans elle, seule une part "
    "de NOTRE portefeuille est calculable — ce qui n'est pas une part de marché, et les confondre "
    "conduirait à des décisions erronées."
)


# ── §2 du CR — Cycle de vie de l'opportunité ────────────────────────────────
#
# L'historique des changements d'étape n'est pas conservé : `opportunities` écrase
# l'étape à chaque mise à jour. Les instantanés nocturnes commencent à accumuler
# la matière (cf. `queries.fetch_mouvements_pipe`) mais ne couvrent que quelques
# jours, et le pipe observé ne bouge presque pas.
#
# La durée par étape ci-dessous est donc un gabarit. La durée création → clôture,
# elle, est MESURÉE sur les 1 360 opportunités portant une `date_closed` : les
# deux ne doivent pas être présentées ensemble sans distinction.
DUREES_ETAPES_STATIQUE = [
    {"etape": "Qualification", "duree_mediane_jours": 12, "part_abandon_pct": 31.0},
    {"etape": "Proposition", "duree_mediane_jours": 21, "part_abandon_pct": 18.0},
    {"etape": "Négociation", "duree_mediane_jours": 18, "part_abandon_pct": 12.0},
    {"etape": "Décision client", "duree_mediane_jours": 34, "part_abandon_pct": 22.0},
]

RAISON_CYCLE_STATIQUE = (
    "L'historique des changements d'étape n'est pas récupéré de l'ERP : le miroir écrase l'étape "
    "précédente à chaque mise à jour. On sait où en est une affaire, pas par où elle est passée. "
    "Les instantanés quotidiens du pipeline ont commencé à constituer cet historique, mais ne "
    "couvrent encore que quelques jours."
)


# ── §6 du CR — Fichier de visite ────────────────────────────────────────────
#
# Aucune table de visite n'existe. Le gabarit sert à trancher les questions 43-47
# du cadrage (qui saisit, quand, quel contenu minimal, rattachement compte ou
# opportunité) sur une forme concrète plutôt que dans l'abstrait.
#
# Les comptes sont réels, les INTERLOCUTEURS sont des fonctions et non des noms
# fabriqués (cf. règle 4 de l'en-tête).
VISITES_STATIQUES = [
    {"date": "2026-08-06", "compte": "ORANGE COTE D'IVOIRE", "interlocuteur": "Direction des systèmes d'information",
     "objet": "Cadrage du renouvellement de l'infrastructure de supervision",
     "prochaine_action": "Remettre la proposition technique avant le 20/08",
     "opportunite_liee": "Renouvellement supervision réseau", "compte_rendu": True},
    {"date": "2026-08-04", "compte": "SOCIETE GENERALE COTE D'IVOIRE", "interlocuteur": "Responsable infrastructure",
     "objet": "Point d'avancement du déploiement des postes de travail",
     "prochaine_action": "Planifier la recette de la phase 2",
     "opportunite_liee": "", "compte_rendu": True},
    {"date": "2026-07-30", "compte": "MTN CI", "interlocuteur": "Direction achats",
     "objet": "Revue de la grille tarifaire cadre",
     "prochaine_action": "Transmettre la grille révisée sous 10 jours",
     "opportunite_liee": "Accord-cadre équipements", "compte_rendu": True},
    {"date": "2026-07-24", "compte": "Banque Africaine de Développement (BAD)",
     "interlocuteur": "Chef de projet infrastructure",
     "objet": "Qualification du besoin datacenter",
     "prochaine_action": "Organiser un atelier technique en septembre",
     "opportunite_liee": "Extension datacenter", "compte_rendu": False},
    {"date": "2026-07-18", "compte": "PETRO IVOIRE", "interlocuteur": "Responsable informatique",
     "objet": "Présentation de l'offre de sauvegarde managée",
     "prochaine_action": "Relancer après arbitrage budgétaire",
     "opportunite_liee": "", "compte_rendu": True},
    {"date": "2026-07-11", "compte": "UEMOA", "interlocuteur": "Direction des services informatiques",
     "objet": "Suivi de l'incident de production et plan de remédiation",
     "prochaine_action": "Livrer le rapport de remédiation avant fin juillet",
     "opportunite_liee": "", "compte_rendu": True},
]

RAISON_VISITES_STATIQUE = (
    "Aucune table de visite n'existe dans le système : ni fichier de visite, ni compte-rendu, ni "
    "rattachement à un compte ou à une opportunité. Il s'agit d'un module de SAISIE destiné aux "
    "commerciaux, distinct du cockpit de pilotage — le traiter séparément permet de livrer plus vite "
    "sur le cockpit lui-même."
)

# Couverture de visite : nombre de mois au-delà duquel un compte est considéré
# comme non couvert. Question 46 du cadrage — le DC veut-il lire les comptes
# rendus, ou seulement suivre ce taux ?
SEUIL_COUVERTURE_VISITE_MOIS = 4
