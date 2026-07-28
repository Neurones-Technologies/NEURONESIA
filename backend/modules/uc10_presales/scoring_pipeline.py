import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from config.settings import settings

from core.ports.llm_gateway import LLMGateway, OutputTruncatedError
from core.services.rag_engine import RAGEngine
from core.domain.offer import (
    ScoringResult,
    ExtractedItem,
    KeyElement,
    MatchedDocument,
    BidRecommendation,
    MarketIdentity,
    CalendarEvent,
    EvaluationModalities,
    ScoringCriterion,
    Risk,
    Precondition,
    Appendix,
    RequiredProfile,
    EligibilityThreshold,
    FinancialData,
)
from core.domain.document import Source
from modules.uc10_presales.latency import timer

logger = logging.getLogger(__name__)


@dataclass
class _AnalysisOutput:
    """DTO interne du résultat de l'étape 4 (évite un tuple à 9 éléments)."""
    gaps_analysis: str
    strengths: list[str]
    risks: list[Risk]
    score: int
    recommendation: BidRecommendation
    justification: str
    criteria: list[ScoringCriterion]
    preconditions: list[Precondition] = field(default_factory=list)
    preconditions_incomplete: bool = False
    # Base du score : GRILLE (somme normalisée), ESTIME (jugement global, AO sans barème),
    # INDISPONIBLE (analyse cassée/tronquée → score neutre 50 à ne pas prendre pour argent comptant).
    score_basis: str = "GRILLE"
    # Scores de préparation par volet (financier/administratif jugés par le LLM ; technique
    # est un alias de `score`, posé côté appelant — cf. run()).
    score_financier: int = 0
    score_administratif: int = 0
    financier_rationale: str = ""
    administratif_rationale: str = ""

# Budgets d'ENTRÉE par étape (en tokens). Haiku 4.5 / Sonnet 4.6 = 200K de contexte,
# PARTAGÉ entre entrée + sortie. Un AO réel (même dense type BAD) fait ~20-40K tokens :
# ces budgets ne tronquent donc quasi jamais en pratique. On les garde larges pour ne
# rien couper, tout en laissant la place à la sortie (analyse = 20K, cf. ci-dessous) et
# au contexte RAG. 150K (entrée) + 20K (sortie) + RAG ≈ très en-deçà des 200K.
_EXTRACT_INPUT_BUDGET_TOKENS = 150_000
_SUMMARY_INPUT_BUDGET_TOKENS = 150_000
# Plus bas pour l'analyse : le prompt y ajoute résumé + grille + contexte RAG à l'AO.
_ANALYZE_INPUT_BUDGET_TOKENS = 120_000

# Budgets de SORTIE (max_tokens). Le plafond n'est PAS une limite du modèle (qui accepte
# des dizaines de milliers de tokens) — c'est un choix coût/sécurité. L'analyse produit le
# JSON le plus volumineux (grille scorée + risques + écarts + préalables) : 20K met le pire
# cas dense très au large, là où 7000 le tronquait en silence → faux score=50.
_ANALYZE_OUTPUT_BUDGET_TOKENS = 20_000
# Résumé exécutif : 2000 (était 1100, 900, 500 — chaque palier s'est avéré court sur un AO
# plus dense que le précédent ; 1100 coupait l'AO GPB-H en plein mot). Si malgré tout la
# sortie est tronquée, retry unique à budget élargi.
_SUMMARY_OUTPUT_BUDGET_TOKENS = 2_000
_SUMMARY_OUTPUT_RETRY_TOKENS = 3_000

# Température 0 sur TOUTES les étapes d'extraction et de notation : ce sont des tâches
# factuelles/structurées où l'on veut la REPRODUCTIBILITÉ (même AO → même grille → même
# score). Le défaut fournisseur (1.0) faisait osciller le score du même AO (ex. 9 vs 25).
_TEMP_DETERMINISTIC = 0.0

# Cohérence score ↔ recommandation : le score plafonne l'optimisme de la reco (un GO à
# 25/100 est incohérent). Le score ≥ _GO_MIN → GO autorisé ; ≥ _CONDITIONAL_MIN → CONDITIONAL ;
# en-dessous → NO_BID. On garde toujours la reco LLM si elle est PLUS prudente que le plafond.
_GO_MIN_SCORE = 60
_CONDITIONAL_MIN_SCORE = 35
# Étape 1b scindée en deux extractions parallèles (sinon un seul JSON — identité+calendrier+
# grille+annexes+profils détaillés+seuils+financier — tronquerait sur AO dense type BAD) :
#  - cadre : identité + calendrier + modalités + grille (volume modéré)
#  - exigences : annexes (jusqu'à ~21) + profils RICHEMENT détaillés (jusqu'à ~14) + seuils + financier
_FRAME_OUTPUT_BUDGET_TOKENS = 6_000
_REQUIREMENTS_OUTPUT_BUDGET_TOKENS = 16_000

# step1.extract (besoins/critères/prérequis/ressources/vigilance) : le retry (8000→12000)
# a un coût de LATENCE réel — observé en prod (SIB) : chaque partie tronquée refait un
# aller-retour LLM COMPLET et SÉQUENTIEL avant de retenter, ce qui a dominé la durée de
# step1.extract (~180s) même après le split par schéma (cf. _EXTRACT_CHUNK_SIZE_TOKENS
# ci-dessous). Or `max_tokens` est un PLAFOND, pas un forfait : une réponse qui se termine
# naturellement à 4000 tokens ne coûte NI plus de temps NI plus cher si le plafond demandé
# est 16000 plutôt que 8000 (le modèle s'arrête à la fin du JSON, pas au plafond) — donc
# partir directement d'un plafond large élimine l'aller-retour de retry dans le cas courant,
# SANS pénaliser les chunks légers. 20000 est déjà validé en prod sans erreur API sur step4
# (cf. _ANALYZE_OUTPUT_BUDGET_TOKENS et test_step4_output_budget.py) : on vise donc large dès
# le premier essai (16000) avec un filet de sécurité au-dessus, plutôt que le patron "petit
# d'abord, élargir ensuite" hérité du résumé exécutif (où ce compromis a du sens : un SEUL
# appel, pas des dizaines par AO en map-reduce).
#
# PLAFOND DUR côté SDK, pas seulement côté modèle : le SDK Anthropic refuse d'exécuter un
# appel NON-streaming au-delà d'un volume de sortie jugé trop long (`_calculate_nonstreaming_
# timeout`, anthropic/_base_client.py) — formule observée en prod : lève ValueError si
# max_tokens > 600 * 128_000 / 3600 ≈ 21333. Cassé en prod ce soir avec 24000 (retry) : le
# ValueError n'était PAS intercepté (seul OutputTruncatedError l'était), ce qui a fait
# planter tout le pipeline au lieu d'abandonner proprement ce chunk. 20000 reste sous ce
# plafond avec marge ; le filet de sécurité doit lui aussi rester strictement en-dessous.
_EXTRACT_OUTPUT_BUDGET_TOKENS = 16_000
_EXTRACT_OUTPUT_RETRY_TOKENS = 20_000

# step1.extract en MAP-REDUCE : sur un AO vraiment dense (SIB 97p, BHCI, LONACI...), même
# le retry à budget de SORTIE élargi (12000) ne suffisait pas — l'AO contient tout
# simplement TROP de besoins/critères/annexes pour tenir dans une seule réponse JSON, qui
# ressortait tronquée ou malformée à chaque tentative (observé en prod à répétition :
# besoins=0/criteres=0 malgré le retry). Découper l'AO en chunks et extraire chaque chunk
# EN PARALLÈLE réduit le volume de sortie PAR APPEL (un chunk a mécaniquement moins
# d'exigences que l'AO entier → moins de risque de dépasser le plafond) sans alourdir la
# latence (les chunks tournent concurremment, pas séquentiellement). Sous ce seuil, l'AO
# tient dans un seul chunk : comportement strictement identique à avant (aucun coût/latence
# ajouté au cas courant).
#
# Taille abaissée de 20 000 → 8 000 tokens : mesuré en prod sur SIB et LONACI, un chunk de
# ~17 600 tokens (moitié d'un AO de 35 200 tokens découpé en 2) débordait ENCORE le plafond
# de sortie élargi (12000) après retry — la densité d'exigences de ces AO ivoiriens est plus
# élevée que l'hypothèse initiale ("~20-40K tokens, tronque rarement"). Des chunks deux fois
# plus petits visent un succès dès le PREMIER essai (pas de retry du tout dans le cas
# courant) plutôt que de re-subir le même échec à une granularité à peine plus fine.
#
# Insuffisant en pratique : observé en prod (LONACI, 2 chunks de ~4750 tokens d'ENTRÉE
# chacun) qu'un chunk peut ENCORE tronquer à 12000 tokens de SORTIE malgré cette réduction —
# la consigne "quasi-verbatim" (cf. RÈGLE ABSOLUE des prompts ci-dessous) fait que la sortie
# structurée peut dépasser l'entrée en volume, indépendamment de la densité du document.
# Réduire encore la taille de chunk ne réglerait que le symptôme. La cause réelle : UN SEUL
# appel JSON porte 7 clés (key_points, criteres_selection, besoins, prerequis,
# ressources_demandees, points_vigilance, date_remise) — même logique que step1b, qui a été
# scindé en cadre/exigences pour la même raison (cf. commentaire plus haut). `besoins` est la
# liste la plus volumineuse observée en prod (116 items sur SIB, contre 73 pour
# criteres_selection) : on la scinde donc dans SON PROPRE appel (avec key_points, léger et
# fixe), le reste (criteres_selection/prerequis/ressources_demandees/points_vigilance/
# date_remise) dans un second appel — les deux tournent EN CONCURRENCE par chunk (asyncio.
# gather, pas de latence ajoutée), chacun avec son propre budget de sortie et son propre
# retry. Un échec sur une moitié n'emporte plus l'autre (avant : tout ou rien par chunk).
_EXTRACT_CHUNK_SIZE_TOKENS = 8_000
_EXTRACT_CHUNK_OVERLAP_TOKENS = 400

_EXTRACT_FIDELITY_RULES = """RÈGLE ABSOLUE — fidélité au texte (quasi-verbatim) :
- Garde les TERMES EXACTS de l'AO. Ne remplace jamais un terme précis par un terme générique.
  ✗ "ingénieurs expérimentés"   ✓ "1 ingénieur étude (5+ ans d'exp.)", "1 spécialiste GLPI certifié"
  ✗ "personnel qualifié"        ✓ "chef de projet BAC+5 (5+ ans)"
  ✗ "bonne expérience"          ✓ "minimum 3 références prouvées par attestations de bonne exécution"
- Conserve TOUT chiffre, durée, seuil, niveau et certification cités : "BAC+5", "5+ ans",
  "3 références", "RTO 8h", "RPO 4h", "12 mois", noms de normes/lois (Sapin II, Convention ONU)...
- Ne FUSIONNE jamais deux exigences distinctes en une seule phrase fourre-tout : un item = une exigence.
- N'INVENTE rien : aucune compétence, certification, technologie, domaine ou chiffre absent du texte.
  Si l'AO reste vague sur un point, reste vague AUSSI (ne comble pas avec ta culture générale)."""

# step1.extract scindé en DEUX prompts (cf. commentaire sur _EXTRACT_CHUNK_SIZE_TOKENS
# ci-dessus) : chacun porte une partie du schéma d'origine, réduisant mécaniquement le volume
# de sortie par appel. Les deux tournent EN CONCURRENCE sur le même chunk (cf.
# `_extract_step1_chunk`), donc aucune latence ajoutée par rapport à l'appel unique d'avant.
_EXTRACT_SYSTEM_BESOINS = """Tu es un extracteur d'appels d'offres IT. Ton rôle est d'EXTRAIRE, pas de RÉSUMER.

OBJECTIF : restituer chaque besoin avec son niveau de détail D'ORIGINE. La valeur métier est
dans les SPÉCIFICITÉS (domaine exact, chiffres, durées, certifications, technologies nommées),
pas dans une formulation générale.

""" + _EXTRACT_FIDELITY_RULES + """

Retourne UN JSON valide :
{
  "key_points": [
    {"label": "Nom court du point", "value": "valeur ou description concise"}
  ],
  "besoins": [{"texte": "besoin fonctionnel ou technique exprimé, détaillé", "source_section": "section/article/page ou ''"}]
}

Pour key_points : identifie 5 à 10 points CRITIQUES propres à CE document.
Choisis librement les labels selon ce que tu trouves — budget, délai, client, secteur, technologie principale,
périmètre géographique, volume, certification requise, type de marché, clause particulière, etc.

RÈGLE source_section (TRAÇABILITÉ) : pour CHAQUE besoin, renseigne `source_section` = D'OÙ vient l'exigence
dans l'AO (n° de section/article/page tel qu'écrit : "Section III Art. 12", "§4.2", "page 8"). Localisation
non identifiable → "" (n'invente JAMAIS une référence).

Réponds UNIQUEMENT avec le JSON valide, sans balises markdown."""

_EXTRACT_SYSTEM_AUTRES = """Tu es un extracteur d'appels d'offres IT. Ton rôle est d'EXTRAIRE, pas de RÉSUMER.

OBJECTIF : restituer chaque exigence avec son niveau de détail D'ORIGINE. La valeur métier est
dans les SPÉCIFICITÉS (domaine exact, chiffres, durées, certifications, technologies nommées),
pas dans une formulation générale.

""" + _EXTRACT_FIDELITY_RULES + """

Retourne UN JSON valide :
{
  "criteres_selection": [{"texte": "critère d'évaluation/sélection, avec ses spécificités et chiffres", "source_section": "section/article/page d'où vient l'exigence ou ''"}],
  "prerequis": [{"texte": "prérequis ou qualification obligatoire, avec niveau/durée/nombre exacts", "source_section": "section/article/page ou ''"}],
  "ressources_demandees": [{"texte": "profil RH demandé avec intitulé exact, spécialité, niveau, expérience", "source_section": "section/article/page ou ''"}],
  "points_vigilance": [{"texte": "risque, contrainte ou point d'attention concret", "source_section": "section/article/page ou ''"}],
  "date_remise": "date limite de remise ou chaîne vide"
}

Pour ressources_demandees : un item PAR profil distinct, avec son intitulé exact (ex: "Ingénieur étude",
"Spécialiste GLPI"), jamais un terme collectif comme "les ingénieurs" ou "l'équipe technique".

RÈGLE source_section (TRAÇABILITÉ) : pour CHAQUE item des 4 listes ci-dessus (criteres_selection, prerequis,
ressources_demandees, points_vigilance), renseigne `source_section` = D'OÙ vient l'exigence dans l'AO (n° de
section/article/page tel qu'écrit : "Section III Art. 12", "§4.2", "page 8"). Localisation non identifiable
→ "" (n'invente JAMAIS une référence). Chaque item = un objet {texte, source_section}.

Réponds UNIQUEMENT avec le JSON valide, sans balises markdown."""

_FRAME_SYSTEM = """Tu es un extracteur du CADRE d'un appel d'offres (identité, calendrier, évaluation, grille).

OBJECTIF : extraire le cadre structuré du marché, EN T'EN TENANT STRICTEMENT À CE QUI EST ÉCRIT.

RÈGLE ABSOLUE — anti-hallucination :
- Si une information n'apparaît PAS littéralement dans le texte → mets `null` (ou 0 pour les nombres, "" pour les chaînes).
- Ne devine JAMAIS, n'extrapole JAMAIS, ne complète JAMAIS avec ta culture générale.
- `confidence` = 1.0 si l'info est citée mot pour mot, 0.7 si elle est paraphrasée/déductible d'un passage explicite, 0.3 si très indirecte, 0.0 si absente.

Retourne UN JSON valide :
{
  "market_identity": {
    "type_marche": "ex: contrat-cadre, marché public de prestation, accord-cadre, RFP... ou ''",
    "reference": "référence/numéro du marché (ex: ADB/RFP/TCGS/2026/0104) ou ''",
    "autorite_contractante": "organisme émetteur ou ''",
    "duree_contrat": "ex: '1 an + 2 renouvellements', '36 mois' ou ''",
    "date_demarrage": "date de démarrage prévue ou ''",
    "deadline_soumission": "date+heure limite de soumission ou ''",
    "validite_offre": "ex: '120 jours' ou ''",
    "perimetre_geographique": "pays/régions du marché ou ''",
    "eligibilite_candidat": "conditions candidat (pays, agréments, groupement) ou ''",
    "confidence": 0.0
  },
  "calendar": [
    {
      "label": "ex: 'Limite questions clarification', 'Visite des lieux', 'Remise offres'",
      "date": "date telle qu'écrite dans l'AO",
      "criticite": "BLOQUANT | CRITIQUE | INFO",
      "source_section": "section/page d'où ça vient (optionnel)"
    }
  ],
  "evaluation_modalities": {
    "ponderation_technique": 0,
    "ponderation_financiere": 0,
    "seuil_minimum_technique": 0,
    "formule_notation_financiere": "ex: 'Nf = 100 × Fm / F' ou ''",
    "modalites": ["ex: 'démo orale obligatoire', 'POC requis', 'présentation équipe'"],
    "confidence": 0.0
  },
  "criteria": [
    {
      "id": "ex: '3.3' (numéro de la grille) ou slug court comme 'ref_similaires'",
      "label": "intitulé du critère d'évaluation",
      "max_points": 0,
      "category": "ex: 'Expérience' / 'RH' / 'Méthodologie' / 'Technique' / 'Offre'",
      "is_inferred": false
    }
  ]
}

Critères de criticité pour calendar :
- BLOQUANT : rater = exclusion automatique (deadline soumission, validité offre)
- CRITIQUE : impact fort sur la réponse (visite des lieux, date des questions)
- INFO : information de planning (démarrage prévu, durée d'évaluation)

GRILLE D'ÉVALUATION (champ `criteria`) — extraire la grille de notation technique :
- Si l'AO contient une grille/barème explicite : extrais CHAQUE critère VERBATIM avec son
  numéro et son nombre de points. `is_inferred` = false. NE PAS inventer de points.
- Si l'AO décrit des critères SANS points chiffrés : extrais les critères, mets max_points=0,
  `is_inferred` = false.
- Si AUCUNE grille n'est présente : dérive 8 à 12 critères standards cohérents avec le type d'AO
  et le secteur, répartis sur 100 points. `is_inferred` = true pour CHACUN.
- N'invente JAMAIS un critère sectoriel précis (ex: "livrables BI") absent du texte.

Si la section "évaluation" n'apparaît pas dans le texte → laisse tous les champs à 0/'' et confidence à 0.0.
Si aucune date n'est trouvée → calendar = [].

Réponds UNIQUEMENT avec le JSON valide, sans balises markdown."""

_REQUIREMENTS_SYSTEM = """Tu es un extracteur d'EXIGENCES CHIFFRÉES ET DÉTAILLÉES d'appels d'offres.
Ces données sont le cœur de valeur de l'analyse : effectifs, compétences, certifications, seuils, montants, pièces.

RÈGLE ABSOLUE — anti-hallucination :
- Ne sors QUE ce qui est littéralement écrit. Info absente → "" / 0 / [].
- N'invente JAMAIS une compétence, une certification, un montant, un effectif ou une pièce non mentionnés.

Retourne UN JSON valide :
{
  "appendices": [
    {
      "code": "ex: '5A', 'Annexe 3' — référence exacte de la pièce, ou ''",
      "label": "intitulé de la pièce/annexe à fournir",
      "type": "ADMIN | TECHNIQUE | FINANCIER | RH",
      "obligatoire": true,
      "langue": "FR | EN | bilingue ou ''",
      "source_section": "section/article d'où vient l'exigence ou ''"
    }
  ],
  "profils_demandes": [
    {
      "profil": "intitulé EXACT (ex: 'Ingénieur Data', 'Analyste Cybersécurité C-SOC')",
      "domaine": "spécialité (ex: 'Data/BI', 'Cybersécurité', 'Réseau') ou ''",
      "quantite": 0,
      "niveau": "ex: 'BAC+5', 'Spécialiste', 'Senior' ou ''",
      "experience_min": "ex: '5 ans', '2 à 4 ans en SOC' ou ''",
      "competences": ["chaque compétence technique exigée pour ce profil"],
      "certifications": ["chaque certification exigée pour ce profil"],
      "missions": ["chaque mission/responsabilité décrite par l'AO"],
      "rattachement": "division/service de rattachement ou ''",
      "source_section": "section d'où vient ce profil ou ''"
    }
  ],
  "seuils_eligibilite": [
    {
      "libelle": "ex: 'Chiffre d'affaires annuel minimum'",
      "valeur": "ex: '500 000 000' — VERBATIM, garde le format exact",
      "unite": "ex: 'FCFA/an', 'références', 'ans'",
      "type": "FINANCIER | EXPERIENCE | REFERENCES | ADMIN | AUTRE",
      "blocking": true,
      "source_section": "section ou ''"
    }
  ],
  "donnees_financieres": {
    "budget_estime": "montant/fourchette si donné, sinon ''",
    "modalites_paiement": "ex: '30% avance, 70% à 30j' ou ''",
    "garantie_soumission": "caution/garantie de soumission exigée ou ''",
    "penalites": "pénalités de retard ou ''",
    "source_section": "section ou ''"
  }
}

PROFILS — détail MAXIMAL, c'est le point le plus important :
- UN objet par poste-type. Si l'AO décrit 14 profils distincts, retourne 14 objets. Ne fusionne pas, ne résume pas.
- Capture CHAQUE compétence, CHAQUE certification, le niveau, la quantité, l'expérience que l'AO précise pour ce profil.
- `quantite` = nombre de postes pour ce profil (0 si l'AO ne le chiffre pas).
- Si l'AO ne liste aucun profil → profils_demandes = [].

SEUILS — tout chiffre conditionnant la recevabilité : CA minimum, nombre de références exigées,
années d'expérience minimales, montant de caution, effectif minimum, etc. `blocking`=true si éliminatoire.

ANNEXES — UNIQUEMENT les pièces explicitement exigées (formulaires, attestations, déclarations,
annexes numérotées). Code/référence EXACT. N'invente aucune pièce générique. Aucune → appendices = [].

Réponds UNIQUEMENT avec le JSON valide, sans balises markdown."""

_SUMMARY_SYSTEM = """Tu es un expert en avant-vente IT. Produis une FICHE DE LECTURE RAPIDE de cet
appel d'offres — pas une note de synthèse en prose. Le lecteur doit saisir l'essentiel en scannant
15 secondes, sans avoir à ouvrir le document ni à lire un pavé de texte qui redonne l'impression de
relire le cahier des charges.

RÈGLE — concret avant tout :
- NOMME les éléments précis du texte : solution/technologie (ex: GLPI, Commvault), client et
  autorité contractante, périmètre chiffré (ex: 7 filiales, 6 pays), contraintes techniques
  chiffrées (ex: RTO 8h, RPO 4h, haute disponibilité), durée, modèle d'évaluation (ex: 70/30).
- Préfère TOUJOURS le terme exact au terme générique : "solution GLPI multi-filiales" plutôt que
  "un outil de gestion" ; "authentification Azure AD/O365" plutôt que "une authentification".
- N'INVENTE rien : ne cite que ce qui est dans le texte. Si une info n'y est pas, ne la mentionne pas.
  Si une section entière n'a pas de contenu pertinent dans l'AO, OMETS-la (jamais de section vide
  ou de "non précisé" en puce).

RÈGLE — format (OBLIGATOIRE, réponds en Markdown) :
- Ligne 1 : une phrase d'accroche en **gras**, le "pitch" du marché en une ligne (qui commande
  quoi, pour quel enjeu) — pas un titre du type "RÉSUMÉ EXÉCUTIF", une vraie phrase.
- Puis des sections courtes, chacune un titre en **gras** suivi de puces Markdown (`- `) :
  **Client & périmètre** (autorité contractante, sites/pays/utilisateurs concernés),
  **Ce qui est demandé** (solution/techno précise, fonctionnalités structurantes),
  **Exigences clés** (seuils techniques et critères éliminatoires — les 3 à 5 plus décisifs,
  pas une liste exhaustive), **Calendrier** (deadline de remise, durée du marché, jalons
  critiques), **Évaluation** (barème chiffré type 70/30, critères de notation). N'inclus que
  les sections qui ont un contenu réel à rapporter.
- Une puce = un fait, une phrase courte. Jamais de sous-liste imbriquée dans une puce, jamais une
  puce qui fait plusieurs lignes. Les énumérations secondaires (modules, certifications) : cite
  les 2-3 plus significatives et agrège le reste (ex. "Deposits, Loans et 4 autres modules
  S/4HANA for Banking") — sans déformer ni inventer.
- Mets en **gras** les chiffres et noms propres qui comptent (deadlines, montants, seuils,
  technologies) pour qu'un lecteur les repère au premier coup d'œil.
- Vise 120 à 180 mots au total (hors titres de section) : c'est un tableau de bord de lecture,
  pas un résumé narratif. Aucune phrase de conclusion nécessaire — la fiche s'arrête à la
  dernière puce utile."""

_ANALYSIS_SYSTEM = """Tu es un directeur commercial senior en IT.
On te fournit une GRILLE D'ÉVALUATION (critères avec points max), nos références (RAG), et les
EXIGENCES FINANCIÈRES/ADMINISTRATIVES chiffrées de l'AO (seuils d'éligibilité, annexes à fournir,
données financières). Évalue NOTRE adéquation à l'AO, critère par critère.

Travail demandé :
1. Pour CHAQUE critère de la grille fournie (identifié par son `id`) : attribue un score estimé
   (entre 0 et son max_points), un niveau de risque, une justification (`rationale`), et la liste
   des fichiers GED qui appuient le score (sources_ged, depuis nos références ; [] si aucune).
   `rationale` : 50 MOTS MAXIMUM — UNE phrase structurée "constat → preuve/manque" (ex: "Deux
   références bancaires récentes couvrent ce critère, mais aucune n'atteint le volume exigé."),
   jamais une liste ni un pavé de plusieurs phrases.
2. Nos forces (ce qu'on maîtrise) et l'analyse des écarts (ce qui manque).
3. Les risques : CHAQUE risque DOIT avoir une mitigation concrète (jamais de risque sans contre-mesure).
   `items_affected` = ids des critères concernés. `pourquoi` et `mitigation` : 50 MOTS MAXIMUM
   chacun — une ou deux phrases denses et concrètes, jamais un paragraphe.
4. Recommandation : GO, NO_BID ou CONDITIONAL.
5. Si recommendation = CONDITIONAL : liste 2 à 5 préalables qui conditionnent le passage en GO
   (sinon preconditions = []).
6. global_adequacy_score : note d'adéquation globale 0-100 (jugement honnête de notre capacité
   à gagner cet AO). Utilisée SEULEMENT si la grille n'a aucun point chiffré (max_points tous à 0) ;
   sinon le score est recalculé depuis la grille. Renseigne-la TOUJOURS.
7. score_financier (0-100) : notre capacité à satisfaire les seuils/exigences FINANCIÈRES du
   volet "Exigences financières/administratives" fourni (CA minimum, garanties, caution de
   soumission, conditions de paiement) au vu de nos références. 100 = large marge sur tous les
   seuils ; note basse = seuil probablement hors de portée ou données financières trop exigeantes.
   Aucune exigence financière listée → 100 (rien à satisfaire). Justifie en une phrase
   (financier_rationale).
8. score_administratif (0-100) : notre capacité à réunir les pièces administratives demandées
   (annexes de type ADMIN, seuils de type ADMIN). Les pièces usuelles d'une société établie
   (RCCM, attestations fiscale/CNPS, statuts) sont quasi toujours disponibles → note haute par
   défaut ; baisse SEULEMENT si l'AO exige un agrément/qualification/certification spécifique et
   rare qu'on ne détient probablement pas. Aucune annexe/seuil administratif listé → 100.
   Justifie en une phrase (administratif_rationale).

Niveaux : risk_level ∈ {FAIBLE, MODÉRÉ, ÉLEVÉ, CRITIQUE} ; criticite ∈ {MODÉRÉ, ÉLEVÉ, CRITIQUE, BLOQUANT}.
N'invente pas de fichier GED absent des références fournies. Reste sobre et factuel.

Réponds UNIQUEMENT en JSON valide :
{
  "criteria": [
    {"id": "3.3", "estimated_score": 5, "risk_level": "ÉLEVÉ",
     "rationale": "Nous n'avons que 2 réf, pas 3", "sources_ged": ["Offre-X.docx"]}
  ],
  "gaps_analysis": "analyse des écarts",
  "strengths": ["force1", "force2"],
  "risks": [
    {"label": "Absence de livrables BI", "criticite": "CRITIQUE",
     "pourquoi": "20 pts dépendent de CVs concrets", "mitigation": "Constituer un GECA partenaire BI",
     "items_affected": ["3.3"]}
  ],
  "recommendation": "CONDITIONAL",
  "justification": "Explication en 2-3 phrases",
  "global_adequacy_score": 45,
  "score_financier": 70,
  "financier_rationale": "CA exigé (500M FCFA) couvert avec marge par nos bilans récents",
  "score_administratif": 90,
  "administratif_rationale": "Pièces standard (RCCM, attestations), aucun agrément rare exigé",
  "preconditions": [
    {"label": "Confirmer CA ≥ 500 M FCFA", "type": "FINANCIER",
     "deadline": "avant J-5", "responsable": "Responsable Financier", "blocking": true}
  ]
}"""


def _fix_json_newlines(s: str) -> str:
    """Échappe les newlines réels dans les valeurs string JSON (LLM met parfois de vrais \\n)."""
    result = []
    in_string = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and in_string and i + 1 < len(s):
            result.append(c)
            result.append(s[i + 1])
            i += 2
            continue
        if c == '"':
            in_string = not in_string
        elif c == "\n" and in_string:
            result.append("\\n")
            i += 1
            continue
        elif c == "\r" and in_string:
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def _truncate_by_tokens(text: str, llm: LLMGateway, max_tokens: int, *, step: str) -> str:
    """Tronque `text` pour tenir dans `max_tokens`. Log un warning si tronqué.

    Estimation par ratio char/token (rapide, ~5% de marge de sécurité) — suffisant
    pour borner le coût ; le décompte exact n'a pas besoin d'être au token près.
    """
    total = llm.count_tokens(text)
    if total <= max_tokens:
        return text
    ratio = (max_tokens / total) * 0.95
    cut = int(len(text) * ratio)
    logger.warning(
        "AO tronqué à l'étape %s : %d tokens > budget %d (texte coupé à %d/%d chars)",
        step, total, max_tokens, cut, len(text),
    )
    return text[:cut]


def _split_into_chunks(text: str, llm: LLMGateway, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    """Découpe `text` en chunks d'environ `chunk_tokens` tokens, avec un recouvrement de
    `overlap_tokens` entre deux chunks consécutifs (limite le risque de couper une exigence
    pile à la frontière). Renvoie `[text]` (un seul chunk) si le texte tient déjà dans
    `chunk_tokens` — pas de découpage inutile pour un AO de taille normale.

    Ratio caractères/token dérivé du texte entier (même approximation que
    `_truncate_by_tokens` — suffisant pour dimensionner des chunks, pas un décompte exact).
    """
    total_tokens = llm.count_tokens(text)
    if total_tokens <= chunk_tokens:
        return [text]
    ratio = len(text) / total_tokens
    chunk_chars = max(1, int(chunk_tokens * ratio))
    overlap_chars = max(0, int(overlap_tokens * ratio))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars
    return chunks


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _dump_failure(raw: str, exc: Exception, step: str) -> Path | None:
    """Sauve la réponse LLM complète sur disque pour analyse forensique.
    Retourne le chemin du fichier ou None si l'écriture a échoué.
    """
    try:
        debug_dir = Path(settings.uploads_path).parent / "debug" / "llm_failures"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"{step}_{ts}.txt"
        path.write_text(
            f"=== Étape : {step} ===\n"
            f"=== Exception : {type(exc).__name__}: {exc} ===\n"
            f"=== Longueur réponse : {len(raw)} chars ===\n"
            f"=== Raw response (complet) ===\n"
            f"{raw}\n",
            encoding="utf-8",
        )
        return path
    except OSError as write_exc:
        logger.error("Impossible de sauvegarder la réponse LLM ratée : %s", write_exc)
        return None


def _clean_json(raw: str) -> str:
    """Extrait le bloc JSON d'une réponse LLM, même avec texte autour."""
    raw = raw.strip()
    # Supprimer les fences markdown
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        raw = raw[first_newline + 1:] if first_newline != -1 else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    # Extraire le premier objet JSON {...} même si le LLM ajoute du texte avant/après
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    # Corriger les newlines réels dans les strings JSON
    raw = _fix_json_newlines(raw)
    # Supprimer les virgules trailing (LLMs en mettent souvent avant } ou ])
    raw = _TRAILING_COMMA_RE.sub(r"\1", raw)
    return raw.strip()



class ScoringPipeline:
    """
    Pipeline de scoring AO en 5 étapes — logique métier pure.
    Utilise LLMGateway (interface) → indépendant du modèle.
    """

    def __init__(self, llm: LLMGateway, rag_engine: RAGEngine, llm_analysis: LLMGateway | None = None):
        # llm : extraction + reranks (tâches mécaniques → Haiku).
        # llm_analysis : ÉTAPE 4 uniquement (analyse/notation/reco = jugement → Sonnet).
        # Repli sur `llm` si non fourni (rétrocompat + tests).
        self._llm = llm
        self._llm_analysis = llm_analysis or llm
        self._rag_engine = rag_engine

    async def _timed(self, label: str, coro):
        """Chronomètre une sous-étape (loggée en `[perf]` si presales_perf_log).

        Purement observationnel : n'altère ni le résultat ni le comportement. Sert à
        localiser la latence par étape (parsing, chaque extraction LLM, matching, analyse).
        """
        with timer(label):
            return await coro

    async def run(self, ao_filename: str, ao_text: str, on_progress=None) -> ScoringResult:
        """`on_progress` (optionnel) : callback async `async def(step: str) -> None`, appelé
        à chaque grande étape du pipeline (cf. `PresalesUseCase.score_ao`)."""
        logger.info("Pipeline scoring démarré pour : %s", ao_filename)

        if on_progress is not None:
            await on_progress("Analyse du contenu (besoins, critères, calendrier)")

        # Étapes 1 + 1b-cadre + 1b-exigences + 2 en parallèle (indépendantes, même input).
        # 1b scindée : le cadre (identité/calendrier/grille) et les exigences chiffrées
        # (annexes/profils/seuils/financier) sont deux JSON distincts pour ne pas tronquer.
        (
            (key_elements, extra),
            (market_identity, calendar, eval_modalities, criteria),
            (appendices, profils_demandes, seuils_eligibilite, donnees_financieres),
            summary,
        ) = await asyncio.gather(
            self._timed("step1.extract", self._step1_extract(ao_text)),
            self._timed("step1b.frame", self._step1b_extract_frame(ao_text)),
            self._timed("step1b.requirements", self._step1b_extract_requirements(ao_text)),
            self._timed("step2.summary", self._step2_summarize(ao_text)),
        )
        logger.info(
            "Steps 1+1b+2 done : key_elements=%d, criteres=%d, besoins=%d, ressources=%d, "
            "calendar=%d events, identity_conf=%.2f (ref='%s' deadline='%s'), eval_conf=%.2f (%d/%d), "
            "profils=%d, seuils=%d, annexes=%d",
            len(key_elements),
            len(extra.get("criteres_selection", [])),
            len(extra.get("besoins", [])),
            len(extra.get("ressources_demandees", [])),
            len(calendar),
            market_identity.confidence,
            market_identity.reference[:40],
            market_identity.deadline_soumission[:30],
            eval_modalities.confidence,
            eval_modalities.ponderation_technique,
            eval_modalities.ponderation_financiere,
            len(profils_demandes),
            len(seuils_eligibilite),
            len(appendices),
        )

        if on_progress is not None:
            await on_progress("Recherche des CV et références similaires")

        # Étape 3a + 3b en parallèle (CVs et projets similaires indépendants)
        # 3a : une recherche CV PAR profil (données riches de l'étape 1b : compétences +
        # certifications + niveau) au lieu d'une requête fusionnée floue → meilleur rappel
        # sur les AO multi-profils.
        project_query = f"{summary} {' '.join(e.value for e in key_elements[:4])}"

        cv_sources, project_sources = await asyncio.gather(
            self._timed(
                "step3.match_cvs",
                self._match_cvs(profils_demandes, extra.get("ressources_demandees", []), summary),
            ),
            self._timed(
                "step3.search_projects",
                self._rag_engine.search_diverse(
                    query=project_query,
                    doc_types=["offre_technique", "abe", "pv_recette", "marches_similaires"],
                    per_type=2,
                    min_dense_score=settings.project_min_similarity,  # levier ① projets
                ),
            ),
        )
        # Levier ③ projets : le LLM écarte les références hors-domaine (ex. ABE Cisco/Fortinet
        # pour un AO Odoo) que le plancher seul ne distingue pas.
        if self._llm and settings.project_llm_rerank and project_sources:
            project_sources = await self._timed(
                "step3.rerank_projects", self._rerank_projects(project_sources, project_query))

        team_matches = [
            MatchedDocument(
                doc_id=s.doc_id,
                filename=s.filename,
                doc_type=s.doc_type.value,
                relevance_score=round(s.relevance_score, 2),
                excerpt=s.excerpt[:500],
            )
            for s in cv_sources
        ]
        logger.debug("Step 3a done : %d CVs matchés", len(team_matches))
        similar_projects = [
            MatchedDocument(
                doc_id=s.doc_id,
                filename=s.filename,
                doc_type=s.doc_type.value,
                relevance_score=round(s.relevance_score, 2),
                excerpt=s.excerpt[:500],
            )
            for s in project_sources
        ]
        logger.debug("Step 3b done : %d projets similaires trouvés", len(similar_projects))

        # matched_documents = union CVs + projets (pour la rétrocompatibilité)
        all_sources = cv_sources + project_sources
        seen: set[str] = set()
        unique_sources = []
        for s in all_sources:
            if s.filename not in seen:
                unique_sources.append(s)
                seen.add(s.filename)
        matched_docs = [
            MatchedDocument(
                doc_id=s.doc_id,
                filename=s.filename,
                doc_type=s.doc_type.value,
                relevance_score=round(s.relevance_score, 2),
                excerpt=s.excerpt[:500],
            )
            for s in unique_sources
        ]

        # Étape 4 & 5 : Analyse + Score. Contexte RAG = CV de l'équipe + projets similaires,
        # pour que les CV pèsent dans la notation des critères RH/profils (sinon le LLM note
        # ces critères sans aucune preuve CV → sources_ged vides).
        # Budgets larges : l'étape analyse a 120K tokens d'entrée et l'AO n'en pèse que ~38K,
        # on peut donc envoyer le contenu réel des CV/offres (et pas des bribes) pour que les
        # critères RH/certifications soient notés sur du concret (cf. faille D).
        with timer("step4.build_context"):
            cv_context, project_context = await asyncio.gather(
                self._rag_engine.build_context(cv_sources, max_tokens=5000),
                self._rag_engine.build_context(project_sources, max_tokens=5000),
            )
        rag_parts = []
        if cv_context:
            rag_parts.append("### CV de notre équipe (GED)\n" + cv_context)
        if project_context:
            rag_parts.append("### Projets & offres similaires (GED)\n" + project_context)
        rag_context = "\n\n".join(rag_parts)
        if on_progress is not None:
            await on_progress("Notation et recommandation finale")
        analysis = await self._timed("step4.analyze", self._step4_analyze(
            ao_text=ao_text,
            summary=summary,
            rag_context=rag_context,
            criteria=criteria,
            seuils_eligibilite=seuils_eligibilite,
            appendices=appendices,
            donnees_financieres=donnees_financieres,
        ))
        logger.info("Pipeline terminé : score=%d, recommandation=%s", analysis.score, analysis.recommendation)

        return ScoringResult(
            ao_filename=ao_filename,
            summary=summary,
            key_elements=key_elements,
            matched_documents=matched_docs,
            gaps_analysis=analysis.gaps_analysis,
            strengths=analysis.strengths,
            risks=analysis.risks,
            score=analysis.score,
            score_basis=analysis.score_basis,
            # Technique = alias du score global (la grille notée EST la grille technique,
            # cf. _FRAME_SYSTEM) ; financier/administratif = jugement LLM dédié (étape 4).
            score_technique=analysis.score,
            score_financier=analysis.score_financier,
            score_administratif=analysis.score_administratif,
            financier_rationale=analysis.financier_rationale,
            administratif_rationale=analysis.administratif_rationale,
            recommendation=analysis.recommendation,
            justification=analysis.justification,
            criteres_selection=extra.get("criteres_selection", []),
            besoins=extra.get("besoins", []),
            prerequis=extra.get("prerequis", []),
            ressources_demandees=extra.get("ressources_demandees", []),
            points_vigilance=extra.get("points_vigilance", []),
            date_remise=extra.get("date_remise", ""),
            team_matches=team_matches,
            similar_projects=similar_projects,
            market_identity=market_identity,
            calendar=calendar,
            evaluation_modalities=eval_modalities,
            criteria_breakdown=analysis.criteria,
            preconditions=analysis.preconditions,
            preconditions_incomplete=analysis.preconditions_incomplete,
            appendices=appendices,
            appendices_incomplete=not appendices,
            profils_demandes=profils_demandes,
            seuils_eligibilite=seuils_eligibilite,
            donnees_financieres=donnees_financieres,
        )

    async def _match_cvs(
        self,
        profils_demandes: list[RequiredProfile],
        ressources_demandees: list[ExtractedItem],
        summary: str,
    ) -> list[Source]:
        """Cherche les CV dans la GED, UNE requête par profil demandé.

        Chaque requête est construite depuis les données riches de l'étape 1b (intitulé +
        domaine + niveau + compétences + certifications) plutôt qu'une requête fusionnée
        floue : meilleur rappel sur les AO multi-profils. Les recherches tournent en
        parallèle, on dédoublonne par fichier en gardant le meilleur score. Repli sur
        ressources_demandees / résumé si aucun profil structuré n'a été extrait.
        """
        queries: list[str] = []
        for p in profils_demandes[:10]:
            parts = [p.profil, p.domaine, p.niveau, p.experience_min]
            parts += list(p.competences[:8]) + list(p.certifications[:6])
            q = " ".join(x for x in parts if x and x.strip()).strip()
            if q:
                queries.append(q)
        if not queries:
            queries = [r.texte for r in ressources_demandees[:6] if r.texte.strip()] \
                or [f"ingénieur {summary[:200]}"]

        results = await asyncio.gather(
            *(
                self._rag_engine.search(
                    query=q, filter_metadata={"doc_type": "cv"}, top_k=4,
                    min_dense_score=settings.cv_min_similarity,  # levier ① : écarte les CV hors-sujet
                )
                for q in queries
            ),
            return_exceptions=True,
        )

        best: dict[str, Source] = {}
        for res in results:
            if isinstance(res, Exception):
                logger.debug("CV search partiel : %s", res)
                continue
            for s in res:
                cur = best.get(s.filename)
                if cur is None or s.relevance_score > cur.relevance_score:
                    best[s.filename] = s
        sources = sorted(best.values(), key=lambda s: s.relevance_score, reverse=True)[:12]
        logger.info("CV matching : %d requête(s) profil → %d CV uniques (post-plancher)", len(queries), len(sources))

        # Levier ③ — re-rank LLM par domaine : le plancher cosinus écarte les CV lointains, mais
        # l'embedder (surtout le fallback) discrimine mal Odoo-vs-réseau. Le LLM tranche.
        if self._llm and settings.cv_llm_rerank and profils_demandes and sources:
            sources = await self._rerank_cvs(sources, profils_demandes)
        return sources

    async def _rerank_cvs(
        self, sources: list[Source], profils_demandes: list[RequiredProfile],
    ) -> list[Source]:
        """Filtre les CV candidats : ne garde que ceux qui correspondent vraiment, par domaine,
        à au moins un profil demandé. Repli non-bloquant sur la liste cosinus si le LLM échoue."""
        profil_lines = []
        for p in profils_demandes[:12]:
            comps = ", ".join((p.competences or [])[:6])
            profil_lines.append(f"- {p.profil} ({p.domaine}) : {comps}".strip())
        cv_lines = []
        for i, s in enumerate(sources):
            # extrait large : les certifications/expériences décisives vivent souvent en fin de CV
            # (ex. « ODOO Functional Certification ») — un snippet trop court les masquerait au juge.
            snippet = " ".join((s.excerpt or "").split())[:2500]
            cv_lines.append(f"[{i}] {s.filename}\n{snippet}")

        system = (
            "Tu es un recruteur technique exigeant. Tu juges si un CV correspond à AU MOINS un "
            "des profils demandés par un appel d'offres. Sois STRICT sur le DOMAINE : un CV "
            "réseau/sécurité (Cisco, Fortinet…) ne correspond PAS à un besoin de développeur ou "
            "consultant ERP/Odoo, et inversement. En cas de doute, marque non pertinent."
        )
        user = (
            "Profils demandés :\n" + "\n".join(profil_lines)
            + "\n\nCV candidats :\n" + "\n\n".join(cv_lines)
            + "\n\nPour CHAQUE CV, indique s'il correspond. Réponds UNIQUEMENT par un objet JSON "
            '{"cvs": [{"i": 0, "relevant": true, "profil": "profil correspondant ou \'\'"}]}.'
        )
        try:
            raw = await self._llm.generate(system=system, user=user, max_tokens=800, temperature=0.0)
            data = json.loads(_clean_json(raw))
            verdicts = {int(v["i"]): bool(v.get("relevant")) for v in data.get("cvs", []) if "i" in v}
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Re-rank CV LLM échoué (%s) — liste cosinus conservée", exc)
            return sources
        kept = [s for i, s in enumerate(sources) if verdicts.get(i, True)]
        logger.info("CV re-rank LLM : %d → %d CV pertinents", len(sources), len(kept))
        return kept

    async def _rerank_projects(self, sources: list[Source], need: str) -> list[Source]:
        """Filtre les projets/offres similaires : ne garde que ceux du MÊME domaine/nature que
        l'AO. Repli non-bloquant sur la liste d'origine si le LLM échoue."""
        proj_lines = []
        for i, s in enumerate(sources):
            snippet = " ".join((s.excerpt or "").split())[:600]
            proj_lines.append(f"[{i}] {s.filename} ({s.doc_type.value})\n{snippet}")
        system = (
            "Tu es un expert avant-vente. Tu juges si un projet/offre passé est une RÉFÉRENCE "
            "PERTINENTE pour un nouvel appel d'offres — c.-à-d. de même NATURE de prestation. "
            "Sois STRICT : une attestation de fourniture d'équipements réseau (Cisco, Fortinet…) "
            "n'est PAS une référence pertinente pour un projet de développement/intégration ERP "
            "ou logiciel, et inversement. En cas de doute, marque non pertinent."
        )
        user = (
            f"Besoin (appel d'offres) :\n{need[:1500]}\n\nProjets/offres candidats :\n"
            + "\n\n".join(proj_lines)
            + "\n\nPour CHAQUE projet, indique s'il est une référence pertinente. Réponds "
            'UNIQUEMENT par un objet JSON {"projets": [{"i": 0, "relevant": true}]}.'
        )
        try:
            raw = await self._llm.generate(system=system, user=user, max_tokens=600, temperature=0.0)
            data = json.loads(_clean_json(raw))
            verdicts = {int(v["i"]): bool(v.get("relevant")) for v in data.get("projets", []) if "i" in v}
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Re-rank projets LLM échoué (%s) — liste conservée", exc)
            return sources
        kept = [s for i, s in enumerate(sources) if verdicts.get(i, True)]
        logger.info("Projets re-rank LLM : %d → %d projets pertinents", len(sources), len(kept))
        return kept

    async def _step1_extract(self, ao_text: str) -> tuple[list[KeyElement], dict]:
        """Extrait besoins/critères/prérequis/ressources/vigilance — en MAP-REDUCE sur les
        AO denses (cf. `_EXTRACT_CHUNK_SIZE_TOKENS`) : un AO de taille normale tient dans un
        seul chunk (comportement identique à avant) ; un AO volumineux est découpé, chaque
        chunk extrait EN PARALLÈLE (chaque chunk lui-même scindé en 2 appels concurrents,
        cf. `_extract_step1_chunk`), puis les résultats fusionnés (cf. `_merge_step1_chunks`).
        """
        empty_extra: dict = {
            "criteres_selection": [], "besoins": [], "prerequis": [],
            "ressources_demandees": [], "points_vigilance": [], "date_remise": "",
        }
        chunks = _split_into_chunks(ao_text, self._llm, _EXTRACT_CHUNK_SIZE_TOKENS, _EXTRACT_CHUNK_OVERLAP_TOKENS)
        if len(chunks) > 1:
            logger.info(
                "step1.extract : AO découpé en %d chunks (map-reduce, %d tokens au total).",
                len(chunks), self._llm.count_tokens(ao_text),
            )
        results = await asyncio.gather(*(self._extract_step1_chunk(c) for c in chunks))
        datas = [d for d in results if d is not None]
        if not datas:
            return [], empty_extra
        return self._merge_step1_chunks(datas)

    async def _extract_step1_chunk(self, snippet: str) -> dict | None:
        """Extrait le JSON step1 sur UN chunk (voir `_step1_extract`) — DEUX appels LLM en
        CONCURRENCE (besoins+key_points d'un côté, le reste de l'autre : cf. commentaire sur
        `_EXTRACT_CHUNK_SIZE_TOKENS`), chacun avec son propre budget/retry via
        `_extract_step1_part`. Fusionne les deux dicts partiels ; un échec sur une moitié
        n'empêche plus l'autre de contribuer (avant le split : tout ou rien par chunk)."""
        snippet = _truncate_by_tokens(snippet, self._llm, _EXTRACT_INPUT_BUDGET_TOKENS, step="extract")
        besoins_data, autres_data = await asyncio.gather(
            self._extract_step1_part(snippet, _EXTRACT_SYSTEM_BESOINS, part="besoins"),
            self._extract_step1_part(snippet, _EXTRACT_SYSTEM_AUTRES, part="autres"),
        )
        if besoins_data is None and autres_data is None:
            return None
        return {**(besoins_data or {}), **(autres_data or {})}

    async def _extract_step1_part(self, snippet: str, system_prompt: str, *, part: str) -> dict | None:
        """Extrait UNE moitié du schéma step1 (voir `_extract_step1_chunk`) sur UN chunk.
        Retry à budget de sortie élargi sur troncature (cf. `_EXTRACT_OUTPUT_RETRY_TOKENS`) —
        couvre aussi le JSON complet mais mal formé (ex. "Expecting ',' delimiter" observé en
        prod sur un AO dense) : ce n'est pas une troncature, mais un nouvel essai à budget
        plus large reste la seule option avant de renoncer honnêtement sur cette moitié — on
        n'invente jamais le contenu manquant."""
        for budget in (_EXTRACT_OUTPUT_BUDGET_TOKENS, _EXTRACT_OUTPUT_RETRY_TOKENS):
            is_last = budget >= _EXTRACT_OUTPUT_RETRY_TOKENS
            try:
                # cacheable=True : le retry (budget élargi) renvoie EXACTEMENT le même
                # system+snippet — cache Anthropic garanti sur la 2e tentative (cf.
                # LLMGateway.generate/extract pour le compromis coût).
                raw = await self._llm.extract(
                    prompt=system_prompt, text=snippet, max_tokens=budget,
                    raise_on_truncation=True, temperature=_TEMP_DETERMINISTIC, cacheable=True,
                )
            except OutputTruncatedError:
                logger.warning(
                    "step1.extract[%s] tronqué au plafond de %d tokens — %s.",
                    part, budget, "abandon de cette partie" if is_last else "retry à budget élargi",
                )
                continue
            except ValueError as exc:
                # Le SDK Anthropic refuse tout appel NON-streaming dont le max_tokens dépasse
                # un plafond calculé côté client (~21333, cf. commentaire sur
                # _EXTRACT_OUTPUT_RETRY_TOKENS) — AVANT même d'envoyer la requête. Sans ce
                # bloc, cette exception remonterait et ferait planter TOUT le pipeline (bug
                # réel en prod ce soir) au lieu d'abandonner proprement cette seule partie.
                logger.warning(
                    "step1.extract[%s] appel refusé par le SDK (%s) au plafond de %d tokens — "
                    "%s.", part, exc, budget,
                    "abandon de cette partie" if is_last else "retry à budget élargi",
                )
                continue
            try:
                return json.loads(_clean_json(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                dump_path = _dump_failure(raw, exc, f"extract_{part}")
                logger.warning(
                    "Extraction JSON[%s] échouée (%s) au plafond de %d tokens — %s. "
                    "Réponse complète sauvée dans %s. Aperçu (2000 chars) :\n%s",
                    part, exc, budget, "abandon de cette partie" if is_last else "retry à budget élargi",
                    dump_path, raw[:2000],
                )
                continue
        return None

    @staticmethod
    def _merge_step1_chunks(datas: list[dict]) -> tuple[list[KeyElement], dict]:
        """Fusionne les résultats step1 de plusieurs chunks (map-reduce) : concatène les
        listes en dédupliquant par texte normalisé (le recouvrement entre chunks peut faire
        ressortir la même exigence deux fois), garde le premier `date_remise` non vide."""

        def _items(d: dict, key: str) -> list[ExtractedItem]:
            """Parse une liste d'exigences en ExtractedItem. Tolère le nouveau format
            [{texte, source_section}] ET l'ancien [str] (robustesse si le LLM régresse) :
            ExtractedItem.coerce gère les deux. Les items au texte vide sont écartés."""
            val = d.get(key, [])
            if not isinstance(val, list):
                return []
            out: list[ExtractedItem] = []
            for v in val:
                item = ExtractedItem.coerce(v)
                if item.texte:
                    out.append(item)
            return out

        def _dedupe(items: list[ExtractedItem]) -> list[ExtractedItem]:
            seen: set[str] = set()
            out: list[ExtractedItem] = []
            for it in items:
                key = re.sub(r"\s+", " ", it.texte.strip().lower())
                if key not in seen:
                    seen.add(key)
                    out.append(it)
            return out

        list_keys = ("criteres_selection", "besoins", "prerequis", "ressources_demandees", "points_vigilance")
        elements: list[KeyElement] = []
        seen_labels: set[str] = set()
        extra: dict = {key: [] for key in list_keys}
        extra["date_remise"] = ""

        for data in datas:
            raw_kp = data.get("key_points", [])
            if isinstance(raw_kp, list):
                for kp in raw_kp:
                    if isinstance(kp, dict):
                        label = str(kp.get("label", "")).strip()
                        value = str(kp.get("value", "")).strip()
                        if label and value and label.lower() not in seen_labels:
                            seen_labels.add(label.lower())
                            elements.append(KeyElement(category=label, value=value))
            for key in list_keys:
                extra[key].extend(_items(data, key))
            if not extra["date_remise"]:
                extra["date_remise"] = str(data.get("date_remise", "")).strip()

        for key in list_keys:
            extra[key] = _dedupe(extra[key])

        return elements, extra

    async def _step1b_extract_frame(
        self, ao_text: str
    ) -> tuple[MarketIdentity, list[CalendarEvent], EvaluationModalities, list[ScoringCriterion]]:
        """Extrait le CADRE : fiche d'identité + calendrier + modalités + grille.

        Prompt strict anti-hallucination : info absente → null/0/'' + confidence abaissée.
        La grille est extraite verbatim si présente, sinon dérivée (is_inferred=True),
        avec filet YAML si le LLM n'en renvoie aucune. Dégradation gracieuse sur échec JSON
        ou troncature (valeurs vides + grille standard) — jamais d'exception.
        """
        snippet = _truncate_by_tokens(ao_text, self._llm, _EXTRACT_INPUT_BUDGET_TOKENS, step="frame")
        try:
            # cacheable=True : gagne sur une ré-analyse forcée du même AO dans les 5 min
            # (cf. LLMGateway.generate/extract) — aucune retry interne à cette étape.
            raw = await self._llm.extract(
                prompt=_FRAME_SYSTEM, text=snippet,
                max_tokens=_FRAME_OUTPUT_BUDGET_TOKENS, raise_on_truncation=True,
                temperature=_TEMP_DETERMINISTIC, cacheable=True,
            )
            data = json.loads(_clean_json(raw))
        except OutputTruncatedError as exc:
            logger.error("Extraction CADRE tronquée (%d tokens) — relever _FRAME_OUTPUT_BUDGET_TOKENS.", exc.max_tokens)
            return MarketIdentity(), [], EvaluationModalities(), self._load_standard_grid()
        except (json.JSONDecodeError, ValueError) as exc:
            dump_path = _dump_failure(raw, exc, "frame")
            logger.warning("Cadre JSON échoué (%s). Réponse sauvée dans %s. Aperçu :\n%s", exc, dump_path, raw[:2000])
            return MarketIdentity(), [], EvaluationModalities(), self._load_standard_grid()

        identity = self._parse_market_identity(data.get("market_identity"))
        calendar = self._parse_calendar(data.get("calendar"))
        evaluation = self._parse_evaluation(data.get("evaluation_modalities"))
        criteria = self._parse_criteria(data.get("criteria")) or self._load_standard_grid()
        if criteria and sum(c.max_points for c in criteria) == 0:
            # Grille non vide mais dégénérée (critères sans le moindre point chiffré,
            # ex. AO qui décrit ses critères en prose sans grille pondérée explicite) —
            # `or` ci-dessus ne l'attrape pas (liste non vide = truthy). Un score sur une
            # grille à 0 point total est structurellement inexploitable (division par
            # zéro évitée en amont, mais le score resterait toujours 0/NO_BID à tort).
            # Repli sur la grille standard ESN, marquée `is_inferred` — jamais présentée
            # comme si elle venait de l'AO.
            logger.warning(
                "Grille extraite mais sans points chiffrés (%d critères, total=0 pt) — "
                "repli sur la grille standard ESN plausible (is_inferred=True).",
                len(criteria),
            )
            criteria = self._load_standard_grid()

        raw_identity = data.get("market_identity") or {}
        raw_eval = data.get("evaluation_modalities") or {}
        logger.info(
            "Frame extracted | identity conf=%.2f (LLM disait %.2f) — %s",
            identity.confidence, float(raw_identity.get("confidence", 0.0) or 0.0),
            self._format_identity(identity),
        )
        logger.info(
            "Frame extracted | evaluation conf=%.2f (LLM disait %.2f) — %s",
            evaluation.confidence, float(raw_eval.get("confidence", 0.0) or 0.0),
            self._format_evaluation(evaluation),
        )
        if calendar:
            logger.info(
                "Frame extracted | calendar %d events — %s",
                len(calendar), " | ".join(f"[{e.criticite}] {e.label} ({e.date})" for e in calendar),
            )
        inferred = sum(1 for c in criteria if c.is_inferred)
        logger.info(
            "Frame extracted | grille %d critères (%d inférés, %d verbatim), total=%d pts",
            len(criteria), inferred, len(criteria) - inferred, sum(c.max_points for c in criteria),
        )
        return identity, calendar, evaluation, criteria

    async def _step1b_extract_requirements(
        self, ao_text: str
    ) -> tuple[list[Appendix], list[RequiredProfile], list[EligibilityThreshold], FinancialData]:
        """Extrait les EXIGENCES CHIFFRÉES : annexes + profils détaillés + seuils + financier.

        Cœur de valeur métier : chaque profil avec quantité/compétences/certifs, chaque seuil
        éliminatoire chiffré, chaque donnée financière — verbatim, jamais inventé. Sortie
        volumineuse (jusqu'à ~14 profils riches + ~21 annexes) → budget large + détection de
        troncature. Dégradation gracieuse sur échec : on rend ce qui a pu être parsé.
        """
        snippet = _truncate_by_tokens(ao_text, self._llm, _EXTRACT_INPUT_BUDGET_TOKENS, step="requirements")
        try:
            # cacheable=True : cf. _step1b_extract_frame ci-dessus (même snippet, même raison).
            raw = await self._llm.extract(
                prompt=_REQUIREMENTS_SYSTEM, text=snippet,
                max_tokens=_REQUIREMENTS_OUTPUT_BUDGET_TOKENS, raise_on_truncation=True,
                temperature=_TEMP_DETERMINISTIC, cacheable=True,
            )
            data = json.loads(_clean_json(raw))
        except OutputTruncatedError as exc:
            logger.error(
                "Extraction EXIGENCES tronquée (%d tokens) — relever _REQUIREMENTS_OUTPUT_BUDGET_TOKENS.",
                exc.max_tokens,
            )
            return [], [], [], FinancialData()
        except (json.JSONDecodeError, ValueError) as exc:
            dump_path = _dump_failure(raw, exc, "requirements")
            logger.warning("Exigences JSON échouées (%s). Réponse sauvée dans %s. Aperçu :\n%s", exc, dump_path, raw[:2000])
            return [], [], [], FinancialData()

        appendices = self._parse_appendices(data.get("appendices"))
        profils = self._parse_profils(data.get("profils_demandes"))
        seuils = self._parse_seuils(data.get("seuils_eligibilite"))
        financial = self._parse_financial(data.get("donnees_financieres"))
        logger.info(
            "Requirements extracted | %d annexes | %d profils (%d postes chiffrés) | %d seuils | budget='%s'",
            len(appendices), len(profils), sum(p.quantite for p in profils), len(seuils),
            financial.budget_estime[:40],
        )
        return appendices, profils, seuils, financial

    @staticmethod
    def _format_identity(i: MarketIdentity) -> str:
        return (
            f"ref='{i.reference}' type='{i.type_marche}' autorite='{i.autorite_contractante}' "
            f"deadline='{i.deadline_soumission}' demarrage='{i.date_demarrage}' "
            f"duree='{i.duree_contrat}' validite='{i.validite_offre}' "
            f"perimetre='{i.perimetre_geographique}' eligibilite='{i.eligibilite_candidat}'"
        )

    @staticmethod
    def _format_evaluation(e: EvaluationModalities) -> str:
        return (
            f"tech={e.ponderation_technique}% fin={e.ponderation_financiere}% "
            f"seuil={e.seuil_minimum_technique}/100 formule='{e.formule_notation_financiere}' "
            f"modalites={e.modalites}"
        )

    @staticmethod
    def _parse_market_identity(raw: object) -> MarketIdentity:
        if not isinstance(raw, dict):
            return MarketIdentity()

        def _s(key: str) -> str:
            val = raw.get(key)
            return str(val).strip() if val not in (None, "null") else ""

        try:
            llm_confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            llm_confidence = 0.0
        llm_confidence = max(0.0, min(1.0, llm_confidence))

        fields = {
            "type_marche": _s("type_marche"),
            "reference": _s("reference"),
            "autorite_contractante": _s("autorite_contractante"),
            "duree_contrat": _s("duree_contrat"),
            "date_demarrage": _s("date_demarrage"),
            "deadline_soumission": _s("deadline_soumission"),
            "validite_offre": _s("validite_offre"),
            "perimetre_geographique": _s("perimetre_geographique"),
            "eligibilite_candidat": _s("eligibilite_candidat"),
        }
        # Confidence dérivée = % de champs effectivement remplis. Pondère deadline+ref+autorité
        # plus fort (critiques pour qualifier un AO).
        critical = ("reference", "deadline_soumission", "autorite_contractante")
        filled_critical = sum(1 for k in critical if fields[k])
        filled_other = sum(1 for k, v in fields.items() if v and k not in critical)
        # max score = 3 critiques * 2 + 6 autres = 12
        derived = (filled_critical * 2 + filled_other) / 12
        # On retient le MIN des deux : le LLM peut sous-estimer (=on respecte),
        # mais ne peut pas sur-estimer par rapport au remplissage réel.
        confidence = min(llm_confidence, derived)
        return MarketIdentity(**fields, confidence=round(confidence, 2))

    @staticmethod
    def _parse_calendar(raw: object) -> list[CalendarEvent]:
        if not isinstance(raw, list):
            return []
        events: list[CalendarEvent] = []
        valid_crit = {"BLOQUANT", "CRITIQUE", "INFO"}
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            date = str(item.get("date", "")).strip()
            if not label or not date:
                continue
            crit = str(item.get("criticite", "INFO")).strip().upper()
            if crit not in valid_crit:
                crit = "INFO"
            events.append(CalendarEvent(
                label=label,
                date=date,
                criticite=crit,
                source_section=str(item.get("source_section", "")).strip(),
            ))
        return events

    @staticmethod
    def _parse_evaluation(raw: object) -> EvaluationModalities:
        if not isinstance(raw, dict):
            return EvaluationModalities()

        def _i(key: str) -> int:
            val = raw.get(key, 0)
            try:
                return max(0, min(100, int(val or 0)))
            except (TypeError, ValueError):
                return 0

        modalites = raw.get("modalites", [])
        if isinstance(modalites, list):
            modalites = [str(m).strip() for m in modalites if str(m).strip()]
        else:
            modalites = []
        try:
            llm_confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            llm_confidence = 0.0
        llm_confidence = max(0.0, min(1.0, llm_confidence))

        pt = _i("ponderation_technique")
        pf = _i("ponderation_financiere")
        seuil = _i("seuil_minimum_technique")
        formule = str(raw.get("formule_notation_financiere", "") or "").strip()

        # Cœur de l'évaluation = les 2 pondérations. Si absentes, c'est inexploitable.
        if pt == 0 and pf == 0:
            derived = 0.1   # effondrement : le LLM peut avoir vu "section éval" sans chiffres
        else:
            # 4 critères possibles, pondération technique+financière = critiques (x2)
            score = (2 if pt > 0 else 0) + (2 if pf > 0 else 0) + (1 if seuil > 0 else 0) \
                + (1 if formule else 0) + (1 if modalites else 0)
            derived = score / 7   # max = 7
        confidence = min(llm_confidence, derived)
        return EvaluationModalities(
            ponderation_technique=pt,
            ponderation_financiere=pf,
            seuil_minimum_technique=seuil,
            formule_notation_financiere=formule,
            modalites=modalites,
            confidence=round(max(0.0, min(1.0, confidence)), 2),
        )

    @staticmethod
    def _parse_criteria(raw: object) -> list[ScoringCriterion]:
        """Parse le bloc `criteria` du LLM en grille. Vide → caller utilise le YAML."""
        if not isinstance(raw, list):
            return []
        criteria: list[ScoringCriterion] = []
        seen_ids: set[str] = set()
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            cid = str(item.get("id", "")).strip() or f"c{idx + 1}"
            # Dédoublonnage des ids (le LLM répète parfois "3.3")
            if cid in seen_ids:
                cid = f"{cid}_{idx + 1}"
            seen_ids.add(cid)
            try:
                max_points = max(0, int(item.get("max_points", 0) or 0))
            except (TypeError, ValueError):
                max_points = 0
            criteria.append(ScoringCriterion(
                id=cid,
                label=label,
                max_points=max_points,
                category=str(item.get("category", "")).strip(),
                is_inferred=bool(item.get("is_inferred", False)),
            ))
        return criteria

    @staticmethod
    def _parse_appendices(raw: object) -> list[Appendix]:
        """Parse le bloc `appendices` (pièces du dossier, extraites verbatim de l'AO)."""
        if not isinstance(raw, list):
            return []
        valid_types = {"ADMIN", "TECHNIQUE", "FINANCIER", "RH"}
        appendices: list[Appendix] = []
        seen: set[str] = set()
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            code = str(item.get("code", "")).strip() or f"A{idx + 1}"
            # Dédoublonnage sur (code, label) — le LLM répète parfois une annexe
            key = f"{code}|{label}".lower()
            if key in seen:
                continue
            seen.add(key)
            atype = str(item.get("type", "ADMIN")).strip().upper()
            if atype not in valid_types:
                atype = "ADMIN"
            obligatoire = item.get("obligatoire", True)
            appendices.append(Appendix(
                code=code,
                label=label,
                type=atype,
                obligatoire=bool(obligatoire) if isinstance(obligatoire, bool) else True,
                langue=str(item.get("langue", "") or "").strip(),
                source_section=str(item.get("source_section", "") or "").strip(),
            ))
        return appendices

    @staticmethod
    def _str_list(raw: object) -> list[str]:
        """Normalise un champ liste-de-strings du LLM (tolère valeur unique ou non-liste)."""
        if isinstance(raw, list):
            return [str(v).strip() for v in raw if str(v).strip()]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return []

    @classmethod
    def _parse_profils(cls, raw: object) -> list[RequiredProfile]:
        """Parse `profils_demandes` : profils richement détaillés extraits verbatim."""
        if not isinstance(raw, list):
            return []
        profils: list[RequiredProfile] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            profil = str(item.get("profil", "") or "").strip()
            if not profil:
                continue
            try:
                quantite = max(0, int(item.get("quantite", 0) or 0))
            except (TypeError, ValueError):
                quantite = 0
            profils.append(RequiredProfile(
                profil=profil,
                domaine=str(item.get("domaine", "") or "").strip(),
                quantite=quantite,
                niveau=str(item.get("niveau", "") or "").strip(),
                experience_min=str(item.get("experience_min", "") or "").strip(),
                competences=cls._str_list(item.get("competences")),
                certifications=cls._str_list(item.get("certifications")),
                missions=cls._str_list(item.get("missions")),
                rattachement=str(item.get("rattachement", "") or "").strip(),
                source_section=str(item.get("source_section", "") or "").strip(),
            ))
        return profils

    @staticmethod
    def _parse_seuils(raw: object) -> list[EligibilityThreshold]:
        """Parse `seuils_eligibilite` : seuils chiffrés conditionnant la recevabilité."""
        if not isinstance(raw, list):
            return []
        valid_types = {"FINANCIER", "EXPERIENCE", "REFERENCES", "ADMIN", "AUTRE"}
        seuils: list[EligibilityThreshold] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            libelle = str(item.get("libelle", "") or "").strip()
            if not libelle:
                continue
            stype = str(item.get("type", "AUTRE")).strip().upper()
            if stype not in valid_types:
                stype = "AUTRE"
            blocking = item.get("blocking", True)
            seuils.append(EligibilityThreshold(
                libelle=libelle,
                valeur=str(item.get("valeur", "") or "").strip(),
                unite=str(item.get("unite", "") or "").strip(),
                type=stype,
                blocking=bool(blocking) if isinstance(blocking, bool) else True,
                source_section=str(item.get("source_section", "") or "").strip(),
            ))
        return seuils

    @staticmethod
    def _parse_financial(raw: object) -> FinancialData:
        """Parse `donnees_financieres` (objet unique). Non-dict → FinancialData vide."""
        if not isinstance(raw, dict):
            return FinancialData()

        def _s(key: str) -> str:
            return str(raw.get(key, "") or "").strip()

        return FinancialData(
            budget_estime=_s("budget_estime"),
            modalites_paiement=_s("modalites_paiement"),
            garantie_soumission=_s("garantie_soumission"),
            penalites=_s("penalites"),
            source_section=_s("source_section"),
        )

    @staticmethod
    def _load_standard_grid(doc_type: str = "regie_it") -> list[ScoringCriterion]:
        """Charge une grille standard depuis data/scoring_grids/<doc_type>.yaml.

        Filet de sécurité quand ni l'AO ni le LLM ne fournissent de grille.
        Tous les critères chargés sont marqués is_inferred=True. Retourne [] si le
        fichier est absent/illisible (jamais d'exception : le scoring continue sans grille).
        """
        grid_path = Path(settings.uploads_path).parent / "scoring_grids" / f"{doc_type}.yaml"
        try:
            data = yaml.safe_load(grid_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Grille standard '%s' illisible (%s) — scoring sans grille", doc_type, exc)
            return []
        raw_criteria = (data or {}).get("criteria", [])
        if not isinstance(raw_criteria, list):
            return []
        criteria: list[ScoringCriterion] = []
        for item in raw_criteria:
            if not isinstance(item, dict) or not str(item.get("label", "")).strip():
                continue
            try:
                max_points = max(0, int(item.get("max_points", 0) or 0))
            except (TypeError, ValueError):
                max_points = 0
            criteria.append(ScoringCriterion(
                id=str(item.get("id", "")).strip() or item["label"][:20],
                label=str(item["label"]).strip(),
                max_points=max_points,
                category=str(item.get("category", "")).strip(),
                is_inferred=True,
            ))
        logger.info("Grille standard '%s' chargée en fallback : %d critères", doc_type, len(criteria))
        return criteria

    async def _step2_summarize(self, ao_text: str) -> str:
        snippet = _truncate_by_tokens(ao_text, self._llm, _SUMMARY_INPUT_BUDGET_TOKENS, step="summarize")
        partial = ""
        for budget in (_SUMMARY_OUTPUT_BUDGET_TOKENS, _SUMMARY_OUTPUT_RETRY_TOKENS):
            try:
                # cacheable=True : cf. step1.extract — même snippet renvoyé tel quel au retry.
                return await self._llm.generate(
                    system=_SUMMARY_SYSTEM,
                    user=snippet,
                    max_tokens=budget,
                    raise_on_truncation=True,
                    temperature=_TEMP_DETERMINISTIC,
                    cacheable=True,
                )
            except OutputTruncatedError as exc:
                partial = exc.partial_text
                logger.warning(
                    "Résumé exécutif tronqué au plafond de %d tokens — %s.",
                    budget,
                    "retry à budget élargi" if budget < _SUMMARY_OUTPUT_RETRY_TOKENS
                    else "récupération à la dernière phrase complète",
                )
        # Toujours tronqué après retry (AO hors norme) : plutôt que d'afficher un mot coupé,
        # on rend le texte partiel arrêté à sa dernière phrase complète.
        cut = partial.rfind(".")
        return partial[: cut + 1] if cut > 0 else partial

    _VALID_RISK_LEVELS = {"FAIBLE", "MODÉRÉ", "ÉLEVÉ", "CRITIQUE"}
    _VALID_CRITICITE = {"MODÉRÉ", "ÉLEVÉ", "CRITIQUE", "BLOQUANT"}

    async def _step4_analyze(
        self,
        ao_text: str,
        summary: str,
        rag_context: str,
        criteria: list[ScoringCriterion],
        seuils_eligibilite: list[EligibilityThreshold] | None = None,
        appendices: list[Appendix] | None = None,
        donnees_financieres: FinancialData | None = None,
    ) -> _AnalysisOutput:
        ao_snippet = _truncate_by_tokens(ao_text, self._llm_analysis, _ANALYZE_INPUT_BUDGET_TOKENS, step="analyze")
        grille_json = json.dumps(
            [{"id": c.id, "label": c.label, "max_points": c.max_points, "category": c.category}
             for c in criteria],
            ensure_ascii=False,
        )
        # Contexte financier/administratif pour score_financier/score_administratif : ne garde
        # que les seuils/annexes des volets concernés (pas les techniques, déjà dans la grille).
        finance_admin_json = json.dumps(
            {
                "seuils_financiers": [
                    {"libelle": s.libelle, "valeur": s.valeur, "unite": s.unite, "blocking": s.blocking}
                    for s in (seuils_eligibilite or []) if s.type == "FINANCIER"
                ],
                "seuils_administratifs": [
                    {"libelle": s.libelle, "valeur": s.valeur, "unite": s.unite, "blocking": s.blocking}
                    for s in (seuils_eligibilite or []) if s.type == "ADMIN"
                ],
                "annexes_administratives": [
                    {"code": a.code, "label": a.label, "obligatoire": a.obligatoire}
                    for a in (appendices or []) if a.type == "ADMIN"
                ],
                "donnees_financieres": {
                    "budget_estime": donnees_financieres.budget_estime if donnees_financieres else "",
                    "modalites_paiement": donnees_financieres.modalites_paiement if donnees_financieres else "",
                    "garantie_soumission": donnees_financieres.garantie_soumission if donnees_financieres else "",
                    "penalites": donnees_financieres.penalites if donnees_financieres else "",
                },
            },
            ensure_ascii=False,
        )
        user_prompt = (
            f"## Résumé de l'AO\n{summary}\n\n"
            f"## Grille d'évaluation (score chaque critère par son id)\n{grille_json}\n\n"
            f"## Exigences financières/administratives (pour score_financier/score_administratif)\n{finance_admin_json}\n\n"
            f"## Nos références (RAG)\n{rag_context}\n\n"
            f"## Extrait AO\n{ao_snippet}"
        )
        # Budget large : 8-15 critères scorés (rationale + sources_ged verbeux) + risques avec
        # mitigation + préalables. Gate (test_step4_output_budget.py) : pire cas dense type ABI
        # mesuré en JSON indenté (comme l'émet Claude). raise_on_truncation=True : si jamais la
        # sortie est coupée au plafond, on le SAIT (OutputTruncatedError) au lieu de subir un
        # JSON tronqué qui retombe en silence sur un faux score=50.
        truncated = False
        try:
            # cacheable=True : gagne sur une ré-analyse forcée du même AO (résumé/grille/RAG
            # déterministes à temp=0, donc souvent identiques d'une ré-analyse à l'autre) —
            # plus faible garantie que sur un retry interne (pas de retry ici), mais aucun
            # coût si le contenu diffère (simple écriture cache, pas de lecture).
            raw = await self._llm_analysis.generate(
                system=_ANALYSIS_SYSTEM,
                user=user_prompt,
                max_tokens=_ANALYZE_OUTPUT_BUDGET_TOKENS,
                raise_on_truncation=True,
                temperature=_TEMP_DETERMINISTIC,
                cacheable=True,
            )
        except OutputTruncatedError as exc:
            truncated = True
            raw = exc.partial_text  # on tentera quand même un parse de récupération
            logger.error(
                "Analyse TRONQUÉE au plafond de %d tokens — sortie incomplète. "
                "Augmenter _ANALYZE_OUTPUT_BUDGET_TOKENS si ça se répète.",
                _ANALYZE_OUTPUT_BUDGET_TOKENS,
            )

        try:
            data = json.loads(_clean_json(raw))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            dump_path = _dump_failure(raw, exc, "analyze")
            cause = "tronquée (plafond tokens atteint)" if truncated else "mal formée"
            logger.warning(
                "Analyse JSON %s (%s). Réponse complète sauvée dans %s. Aperçu (2000 chars) :\n%s",
                cause, exc, dump_path, raw[:2000],
            )
            # Dégradation gracieuse : grille non scorée + score neutre EXPLICITEMENT marqué
            # INDISPONIBLE (≠ vraie note de 50) pour que le front ne l'affiche pas comme un score réel.
            justification = (
                "Analyse tronquée : le document a dépassé la capacité de sortie. "
                "Relancez ou réduisez le périmètre."
                if truncated else
                "Analyse indisponible (réponse mal formée) — veuillez réessayer."
            )
            return _AnalysisOutput(
                gaps_analysis="", strengths=[], risks=[], score=50,
                recommendation=BidRecommendation.CONDITIONAL,
                justification=justification,
                criteria=criteria, preconditions=[], preconditions_incomplete=False,
                score_basis="INDISPONIBLE",
            )

        rec_str = str(data.get("recommendation", "CONDITIONAL")).upper()
        try:
            recommendation = BidRecommendation(rec_str)
        except ValueError:
            recommendation = BidRecommendation.CONDITIONAL

        def _to_list(val) -> list[str]:
            return [str(v).strip() for v in val if str(v).strip()] if isinstance(val, list) else []

        scored_criteria = self._merge_criteria_scores(criteria, data.get("criteria"))
        risks = self._parse_risks(data.get("risks"))
        preconditions = self._parse_preconditions(data.get("preconditions"))

        # Score global = somme des scores estimés, normalisée sur 100 (cohérence intrinsèque).
        # On ne somme QUE les critères feuilles : si la grille a des critères hiérarchiques
        # (ex. '2' parent de '2.1','2.2'), le parent ET ses enfants sont tous deux extraits,
        # ce qui doublerait les points (ex. total=145 au lieu de 100). On exclut donc les
        # parents qui ont au moins un sous-critère chiffré. Repli sur l'ensemble si ce filtre
        # vide le barème (grille non hiérarchique ou enfants à 0 point).
        scoring_criteria = self._leaf_criteria(scored_criteria)
        total_max = sum(c.max_points for c in scoring_criteria)
        total_est = sum(c.estimated_score for c in scoring_criteria)
        if total_max == 0:
            scoring_criteria = scored_criteria
            total_max = sum(c.max_points for c in scoring_criteria)
            total_est = sum(c.estimated_score for c in scoring_criteria)
        if total_max > 0:
            score = max(0, min(100, round(100 * total_est / total_max)))
            score_basis = "GRILLE"
        else:
            # Pas de barème chiffré (ex: AO sans grille pondérée) → on n'invente PAS un 50 trompeur.
            # On retient la note d'adéquation globale jugée par le LLM, marquée ESTIME. Si même
            # celle-ci est absente, on tombe sur 50 mais explicitement INDISPONIBLE.
            adequacy = data.get("global_adequacy_score")
            try:
                adequacy_int = int(adequacy) if adequacy is not None else None
            except (TypeError, ValueError):
                adequacy_int = None
            if adequacy_int is not None:
                score = max(0, min(100, adequacy_int))
                score_basis = "ESTIME"
                logger.warning(
                    "Aucune grille chiffrée (max=0) — score d'adéquation global LLM retenu : %d", score,
                )
            else:
                score = 50
                score_basis = "INDISPONIBLE"
                logger.warning(
                    "Aucune grille chiffrée NI score d'adéquation — score neutre 50 (INDISPONIBLE)",
                )

        # Cohérence score ↔ recommandation : un GO à 25/100 est contradictoire (le score et la
        # reco sont produits séparément). On ramène la reco au plafond autorisé par le score.
        coherent = self._coherent_recommendation(score, recommendation)
        if coherent != recommendation:
            logger.info(
                "Recommandation LLM '%s' incohérente avec score=%d → ramenée à '%s'.",
                recommendation.value, score, coherent.value,
            )
            recommendation = coherent

        # Cohérence : les préalables conditionnent le passage CONDITIONAL → GO. Ils n'ont pas de
        # sens pour un GO (on répond tel quel) ni un NO_BID (on ne répond pas). Si le LLM en
        # renvoie quand même, on les écarte pour ne pas afficher de préalables sur un NO_BID/GO.
        if recommendation != BidRecommendation.CONDITIONAL and preconditions:
            logger.info(
                "Recommandation %s avec %d préalable(s) — écartés (pertinents seulement en CONDITIONAL).",
                recommendation.value, len(preconditions),
            )
            preconditions = []

        # Garde-fou : CONDITIONAL sans préalables → on flague, PAS de reprompt (dégradation gracieuse).
        preconditions_incomplete = recommendation == BidRecommendation.CONDITIONAL and not preconditions
        if preconditions_incomplete:
            logger.warning("Recommandation CONDITIONAL sans préalables — flag preconditions_incomplete=True")

        # Scores de préparation financier/administratif : jugement LLM, repli à 100 (rien à
        # satisfaire) si absent/mal formé plutôt qu'un 0 trompeur qui laisserait croire à un échec.
        def _pct(key: str) -> int:
            try:
                return max(0, min(100, int(data.get(key, 100))))
            except (TypeError, ValueError):
                return 100

        score_financier = _pct("score_financier")
        score_administratif = _pct("score_administratif")

        logger.info(
            "Step4 done | score=%d (%d/%d pts, basis=%s), fin=%d, admin=%d, rec=%s, "
            "%d critères scorés, %d risques, %d préalables",
            score, total_est, total_max, score_basis, score_financier, score_administratif,
            recommendation.value, len(scored_criteria), len(risks), len(preconditions),
        )
        return _AnalysisOutput(
            gaps_analysis=str(data.get("gaps_analysis", "") or "").strip(),
            strengths=_to_list(data.get("strengths")),
            risks=risks,
            score=score,
            recommendation=recommendation,
            justification=str(data.get("justification", "") or "").strip(),
            criteria=scored_criteria,
            preconditions=preconditions,
            preconditions_incomplete=preconditions_incomplete,
            score_basis=score_basis,
            score_financier=score_financier,
            score_administratif=score_administratif,
            financier_rationale=str(data.get("financier_rationale", "") or "").strip(),
            administratif_rationale=str(data.get("administratif_rationale", "") or "").strip(),
        )

    @staticmethod
    def _coherent_recommendation(score: int, llm_reco: BidRecommendation) -> BidRecommendation:
        """Plafonne la recommandation selon le score, sans jamais la rendre plus optimiste.

        Le score borne l'optimisme (pas de GO sur un dossier faible), mais on respecte une
        reco LLM PLUS prudente que le plafond (le LLM peut connaître un motif bloquant non
        chiffré, ex. inéligibilité). Tue les incohérences type « 25/100 + GO ».
        """
        if score >= _GO_MIN_SCORE:
            ceiling = BidRecommendation.GO
        elif score >= _CONDITIONAL_MIN_SCORE:
            ceiling = BidRecommendation.CONDITIONAL
        else:
            ceiling = BidRecommendation.NO_BID
        order = {BidRecommendation.NO_BID: 0, BidRecommendation.CONDITIONAL: 1, BidRecommendation.GO: 2}
        # min(reco, plafond) : on garde la plus prudente.
        return ceiling if order[llm_reco] > order[ceiling] else llm_reco

    @staticmethod
    def _leaf_criteria(criteria: list[ScoringCriterion]) -> list[ScoringCriterion]:
        """Retourne les critères feuilles : exclut tout critère parent d'un autre via son id.

        Un critère d'id 'X' est parent si un autre critère a un id commençant par 'X.'
        (ex. '2' parent de '2.1'). Évite le double comptage des points dans une grille
        hiérarchique (section + sous-critères tous deux extraits depuis le tableau de notation).
        """
        ids = [c.id for c in criteria]

        def _has_child(cid: str) -> bool:
            prefix = cid + "."
            return any(other != cid and other.startswith(prefix) for other in ids)

        return [c for c in criteria if not _has_child(c.id)]

    def _merge_criteria_scores(
        self, criteria: list[ScoringCriterion], raw: object
    ) -> list[ScoringCriterion]:
        """Fusionne les scores LLM (par id) dans la grille extraite en 1b."""
        by_id: dict[str, dict] = {}
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and str(item.get("id", "")).strip():
                    by_id[str(item["id"]).strip()] = item
        for c in criteria:
            scored = by_id.get(c.id)
            if not scored:
                continue
            try:
                c.estimated_score = max(0, min(c.max_points, int(scored.get("estimated_score", 0) or 0)))
            except (TypeError, ValueError):
                c.estimated_score = 0
            level = str(scored.get("risk_level", "")).strip().upper()
            if level in self._VALID_RISK_LEVELS:
                c.risk_level = level
            c.rationale = self._cap_words(str(scored.get("rationale", "") or "").strip())
            srcs = scored.get("sources_ged", [])
            if isinstance(srcs, list):
                c.sources_ged = [str(s).strip() for s in srcs if str(s).strip()]
        return criteria

    _RATIONALE_MAX_WORDS = 50

    @classmethod
    def _cap_words(cls, text: str, max_words: int = _RATIONALE_MAX_WORDS) -> str:
        """Garde-fou déterministe : tronque à `max_words` mots même si le LLM ignore la
        consigne du prompt (50 mots max pour `rationale`/`pourquoi`/`mitigation` — texte
        dense, pas un paragraphe)."""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + "…"

    def _parse_risks(self, raw: object) -> list[Risk]:
        if not isinstance(raw, list):
            return []
        risks: list[Risk] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            crit = str(item.get("criticite", "MODÉRÉ")).strip().upper()
            if crit not in self._VALID_CRITICITE:
                crit = "MODÉRÉ"
            mitigation = self._cap_words(str(item.get("mitigation", "") or "").strip())
            if not mitigation:
                logger.warning("Risque sans mitigation : '%s' (garde-fou : conservé tel quel)", label[:60])
            affected = item.get("items_affected", [])
            affected = [str(a).strip() for a in affected if str(a).strip()] if isinstance(affected, list) else []
            risks.append(Risk(
                label=label, criticite=crit,
                pourquoi=self._cap_words(str(item.get("pourquoi", "") or "").strip()),
                mitigation=mitigation, items_affected=affected,
            ))
        return risks

    @staticmethod
    def _parse_preconditions(raw: object) -> list[Precondition]:
        if not isinstance(raw, list):
            return []
        valid_types = {"FINANCIER", "ADMIN", "TECHNIQUE", "PARTENARIAT"}
        preconditions: list[Precondition] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            ptype = str(item.get("type", "ADMIN")).strip().upper()
            if ptype not in valid_types:
                ptype = "ADMIN"
            preconditions.append(Precondition(
                label=label, type=ptype,
                deadline=str(item.get("deadline", "") or "").strip(),
                responsable=str(item.get("responsable", "") or "").strip(),
                status="PENDING",
                blocking=bool(item.get("blocking", False)),
            ))
        return preconditions
