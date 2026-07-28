"""
Contrat template ↔ générateur (UC10 Pre-Sales).

Source UNIQUE de vérité des éléments structurels qu'un template d'offre `.docx`
DOIT contenir pour être rempli correctement par `offer_generator.OfferGenerator`.

Ce module est consommé à la fois par :
  - le générateur (`offer_generator.py`) — pour remplir le document ;
  - le validateur (`template_validator.py`) — pour vérifier un `.docx` avant usage ;
  - la documentation (`TEMPLATE-OFFRE-TECHNIQUE.md`) — qui décrit ces mêmes règles.

Centraliser ces constantes évite que le code, le validateur et la doc dérivent.
"""

# ── Domaines ──────────────────────────────────────────────────────────────────
DEFAULT_DOMAIN = "Digitalisation"
DOMAINS = ["Digitalisation", "Infrastructure", "Cybersécurité", "Cloud"]

# ── Noms « legacy » à remplacer par le nom du client ──────────────────────────
# Doivent apparaître dans le template (corps + page de garde + en-têtes) pour que
# la substitution du nom du client fonctionne.
LEGACY_NAMES = [
    "BGFI BANK", "BGFI", "KORAZ PARTNERS", "KORAZ PARTNER", "KORAZ", "SOCOPRIM",
]

# Mots-clés permettant de localiser le TITRE legacy (page de garde / en-têtes).
LEGACY_TITLE_KEYWORDS = [
    "ticket restaurant", "solution de ticket", "gestion de ticket",
    "application de ticket", "conception d",
]

# ── Ancres de titres (headings) — ordre attendu dans le document ──────────────
# Le générateur localise chaque section variable par le TEXTE de son heading
# (comparaison normalisée : casse / accents / apostrophes / tirets ignorés).
# Renommer ou supprimer une ancre = section non remplie.
H_BESOINS      = "EXPRESSION DES BESOINS"
H_OBJECTIFS    = "OBJECTIFS DE NEURONES TECHNOLOGIES"
H_PRESENTATION = "PRESENTATION DE LA REPONSE DE NEURONES TECHNOLOGIES"
H_DESCRIPTION  = "Description détaillée de la solution proposée"
H_METHODOLOGIE = "MÉTHODOLOGIE DE TRAVAIL ET DESCRIPTION DES SERVICES"

# Ancres requises, dans l'ordre. H_METHODOLOGIE sert de borne de fin (section
# « Description détaillée ») et n'est pas réécrite mais doit exister.
REQUIRED_HEADINGS = [
    H_BESOINS, H_OBJECTIFS, H_PRESENTATION, H_DESCRIPTION, H_METHODOLOGIE,
]

# ── Planning : noms de phases (lignes du dernier tableau) ─────────────────────
# Doivent correspondre EXACTEMENT (après normalisation) aux lignes du tableau de
# planning, sinon les J/H ne sont pas mis à jour pour la phase concernée.
PLANNING_PHASES = [
    "PREALABLE",
    "PLANIFICATION",
    "CADRAGE",
    "IMPLEMENTATION",
    "FORMATION",
    "VALIDATION DE LA RECETTE ET PERIODE D'OBSERVATION",
    "GESTION DE PROJET",
]

# ── Tableaux ──────────────────────────────────────────────────────────────────
# Ordre = position dans le document : composants (index 0), équipe (1), planning.
# Le tableau de planning est localisé par CONTENU (présence des phases), pas par
# position : un .docx peut contenir d'autres tableaux après le planning.
MIN_TABLES = 3
TECH_TABLE_DATA_ROWS = 5        # lignes de stack mises à jour dans le tableau composants
PLANNING_MIN_PHASES_MATCH = 3   # nb min de phases trouvées pour reconnaître le tableau planning


# ── Templates « à variables » {{ }} ──────────────────────────────────────────
# Certains templates (ex. Offre_Technique_template.docx) ne s'appuient PAS sur les
# noms legacy + ancres de titres ci-dessus, mais sur des placeholders {{ }} que le
# générateur substitue (détection automatique : présence d'un {{ dans le .docx).
#
# Les clés ci-dessous sont la forme LISIBLE des placeholders ; le moteur les compare
# en forme NORMALISÉE (casse / accents / apostrophes / espaces ignorés), ce qui rend
# le matching tolérant aux variantes du modèle (ex. « {{Nom client }} » avec espace).
PH_TITRE          = "Titre de l'offre"
PH_CLIENT         = "Nom client"
PH_MOIS           = "Mois"
PH_ANNEE          = "Année"
PH_BESOINS        = "Expression du besoin"   # le template porte la typo « besion » : on accepte les deux
PH_BESOINS_TYPO   = "Expression du besion"
PH_PROPOSITION    = "Proposition de Neurones technologies"
PH_FONCTIONNALITES = "fonctionnalités de la solution"
PH_REPARTITION    = "Répartition des fonctionnalités"

# Placeholders attendus par le validateur quand le template est « à variables ».
EXPECTED_PLACEHOLDERS = [
    PH_TITRE, PH_CLIENT, PH_MOIS, PH_ANNEE,
    PH_BESOINS, PH_PROPOSITION, PH_FONCTIONNALITES, PH_REPARTITION,
]

# En-têtes du tableau Fonctionnalité → Composant inséré à {{Répartition...}}.
REPARTITION_HEADERS = ("Fonctionnalité", "Composant / Couche technique")
