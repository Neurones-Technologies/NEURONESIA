import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete, func

from api.v1.dependencies import CurrentUser
from modules.uc02_capital_knowledge.schemas import ChatRequest, ChatResponse, SourceSchema
from modules.uc02_capital_knowledge.use_case import CapitalKnowledgeUseCase
from core.services.query_dispatcher import _classify_intent_rules
from config.settings import settings
from db.database import AsyncSessionLocal
from db.models import ConversationModel
from core.services.sql_guard import SqlGuardError
from core.services.sql_schema import KB_DDL, KB_TABLES, ODOO_TABLES

# ── Patterns pour pre-fetch CRM sans appel LLM ────────────────────────────────
_RE_ORDER_REF = re.compile(r'\bFP/\d{4}/\d+\b', re.IGNORECASE)
_RE_ARTICLES_QUERY = re.compile(
    r'articles?|lignes?\s+de\s+commande|d[eé]tails?\s+(?:du|de\s+la|de\s+ce)\s+bon|'
    r'produits?\s+(?:command[eé]s?|du\s+bon)|qu[\'e]\s+(?:contient|y\s+a)',
    re.IGNORECASE,
)
_RE_RECENT_ORDERS = re.compile(
    r'derni[eè]res?\s+commandes?|commandes?\s+r[eé]centes?|dernier[es]?\s+achat|commandes?\s+client',
    re.IGNORECASE,
)
_RE_TOP_CLIENTS = re.compile(
    r'top\s+clients?|meilleurs?\s+clients?|plus\s+gros?\s+clients?|plus\s+importants?\s+clients?',
    re.IGNORECASE,
)
_RE_UNPAID = re.compile(
    r'factures?\s+impay[eé]es?|impay[eé]s?|en\s+attente\s+de\s+paiement',
    re.IGNORECASE,
)
_RE_GLOBAL_STATS = re.compile(
    r'(?:combien\s+(?:de\s+)?clients?|statistiques?\s+globales?|chiffre\s+d.affaires?\s+total|bilan\s+global)',
    re.IGNORECASE,
)
# Détection query client-spécifique : "historique de X", "données de X", "parle moi de X", etc.
_RE_CLIENT_QUERY = re.compile(
    r'(?:historique|commandes?|factures?|achats?|donn[e\xe9]es?|infos?\s+sur'
    r'|parle\s+(?:moi\s+)?(?:des?|du|de)?'
    r'|quel(?:le)?\s+est\s+le\s+ca\s+de'
    r'|combien\s+a\s+command[e\xe9]'
    r'|sais\s+(?:tu\s+)?qui\s+est\s+le\s+\w+\s+sur'
    r'|qui\s+(?:est\s+(?:le\s+)?(?:commercial|responsable|gestionnaire|contact)\s+(?:de|sur|pour)'
    r'|s\'occupe\s+de|g[e\xe8]re)'
    r')\s+(?:du\s+client\s+|de\s+(?:la\s+|l\'|l[e\xe9]\s+)?(?:soci[e\xe9]t[e\xe9]\s+)?|pour\s+)?'
    r'([A-Z][A-Za-z0-9\s&.\',\-]{1,50})',
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["UC02 - Capital Knowledge"])


def _dedup_sources_for_display(sources: list) -> list:
    """Citations utilisateur : un seul extrait par fichier (le mieux classé).
    La recherche peut remonter plusieurs chunks d'un même document — utile pour
    le contexte LLM, mais redondant à l'affichage."""
    seen: set[str] = set()
    out = []
    for s in sources:
        if s.filename in seen:
            continue
        seen.add(s.filename)
        out.append(s)
    return out


async def _parse_uploaded_files(
    files: list[UploadFile],
    pdf_parser,
    docx_parser,
) -> list[dict]:
    """Parse les fichiers joints et retourne leur contenu texte. Max 3 fichiers, 15 000 chars chacun."""
    if not files:
        return []
    results = []
    tmp_dir = Path(settings.uploads_path) / "chat_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for f in files[:3]:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in (".pdf", ".docx", ".doc", ".txt"):
            logger.warning("Type de fichier non supporté : %s", f.filename)
            continue
        tmp_path = tmp_dir / f"chat_{uuid.uuid4().hex}{ext}"
        try:
            tmp_path.write_bytes(await f.read())
            if ext == ".pdf":
                text = await pdf_parser.parse(str(tmp_path))
            elif ext in (".docx", ".doc"):
                text = await docx_parser.parse(str(tmp_path))
            else:
                text = tmp_path.read_text(errors="ignore")
            if text.strip():
                results.append({"filename": f.filename, "content": text[:15_000]})
                logger.info("Fichier joint parsé : %s (%d chars)", f.filename, len(text))
        except Exception as exc:
            logger.warning("Parsing %s échoué : %s", f.filename, exc)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    return results

def _get_system_prompt() -> str:
    """Génère le system prompt avec la date du jour injectée dynamiquement."""
    from datetime import datetime as _dt
    _now = _dt.now()
    _quarter = (_now.month - 1) // 3 + 1
    return (
        f"Tu es Neurones IA, l'assistant IA interne de Neurones Technologies (ESN en Côte d'Ivoire).\n"
        f"Date du jour : {_now.strftime('%d/%m/%Y')} — Trimestre en cours : Q{_quarter} {_now.year}\n\n"
        "Tu n'es PAS Claude, tu n'es PAS un assistant généraliste. "
        "Tu es connecté à la base de données Odoo de Neurones Technologies "
        "(clients, factures, bons de commande avec leurs articles) et à la GED interne.\n\n"

        "DONNÉES DISPONIBLES DANS TES OUTILS :\n"
        "- Clients, bons de commande (avec lignes produits), factures, pipeline CRM\n"
        "- Calcul de rétention/churn clients, performance commerciaux (avec filtre trimestre), prévision CA\n"
        "- Analyse de risque client (score 0-100), CA par secteur, CA par produit, cross-sell\n"
        "- GED : CVs ingénieurs, offres techniques, PV de réception, procédures\n\n"

        "DONNÉES NON DISPONIBLES (dire honnêtement, ne jamais inventer) :\n"
        "- Coûts d'achat / marges nettes (non synchronisés depuis Odoo)\n"
        "- Données RH (effectifs, salaires, organigramme)\n"
        "- NPS / satisfaction client / enquêtes\n"
        "- Délais de livraison réels vs contractuels\n\n"

        "RÈGLE ABSOLUE — ANTI-HALLUCINATION : "
        "Ne JAMAIS inventer, compléter ou déduire des données non présentes dans les résultats d'outils. "
        "Si un outil retourne 50 résultats sur 200, affiche UNIQUEMENT ces 50 réels. "
        "L'exactitude prime sur l'exhaustivité.\n\n"

        "COMPORTEMENT D'UN VRAI AGENT — AVANT DE DIRE 'JE NE SAIS PAS' :\n"
        "1. Vérifie d'abord si un outil spécialisé couvre la question (plus rapide et fiable).\n"
        "2. Si aucun outil spécialisé ne convient, utilise 'executer_analyse_sql' pour écrire la requête SQL exacte.\n"
        "   Exemples de ce que tu peux calculer toi-même avec SQL :\n"
        "   • Taux de rétention, churn, nouveaux clients → analyser_evolution_clients OU SQL sur sale_orders\n"
        "   • CA par mois/trimestre/secteur/commercial avec n'importe quel filtre → SQL\n"
        "   • Clients ayant commandé X mais pas Y → SQL avec NOT IN + json_each\n"
        "   • Délai moyen entre deux événements (invoice_date → payment_date) → SQL AVG()\n"
        "   • Classements croisés (ex: top clients d'un secteur sur une période) → SQL GROUP BY + ORDER BY\n"
        "   • Toute question analytique inédite → écris le SQL adapté\n"
        "2bis. DEUX bases SQL distinctes — choisis le bon outil :\n"
        "   • executer_analyse_sql → données COMMERCIALES Odoo (ventes, factures, bons de commande, dossiers, CA, marges).\n"
        "   • interroger_documents → données DOCUMENTAIRES GED (kb_*) : compter/filtrer/CROISER CV, appels d'offres, "
        "attestations de bonne exécution, certifications, PV de recette, comptes rendus "
        "(ex. 'attestations > 200M sur 3 ans', 'consultants PMP ayant fait du bancaire', 'certifs expirant en 2026'). "
        "Cite alors les documents sources (doc_id + fichier_source) renvoyés par la requête.\n"
        "   • Tu peux combiner les deux (hybride) pour une question mêlant commercial et documents.\n"
        "3. Tu peux enchaîner plusieurs outils : d'abord SQL pour les données brutes, puis synthèse.\n"
        "4. Spécifie TOUJOURS la période couverte dans chaque réponse chiffrée.\n"
        "5. Si des données CRM sont déjà dans le message (section '## Données CRM'), utilise-les sans appeler d'outil.\n\n"

        "PROFILS / CV — RACONTER TOUTE L'HISTOIRE DE LA PERSONNE :\n"
        "Quand on te demande de DÉCRIRE, PRÉSENTER ou PARLER du profil/CV d'UNE personne précise "
        "('présente-moi X', 'décris le CV de Y', 'qui est Z', 'parle-moi de W') :\n"
        "1. Identifie la personne si besoin (rechercher_documents_ged ou interroger_documents), puis "
        "APPELLE 'obtenir_profil_complet' (avec le nom ou le doc_id) — il renvoie le CV INTÉGRAL.\n"
        "2. Restitue alors TOUT le parcours, pas seulement le fragment recherché : synthèse du profil, "
        "expériences (du plus récent au plus ancien, avec client/secteur/rôle), formations, certifications, "
        "compétences clés. Le but est de raconter l'histoire complète de la personne.\n"
        "3. N'utilise PAS 'obtenir_profil_complet' pour COMPTER/FILTRER des CV (→ interroger_documents). "
        "Quand la question vise PLUSIEURS personnes (ex. 'les profils DevOps') : donne d'abord une LISTE "
        "avec un résumé court par personne, puis le profil complet uniquement sur la personne ciblée ou à la demande.\n\n"

        "RÈGLE ABSOLUE — BRIÈVETÉ :\n"
        "N'écris AUCUN texte avant d'avoir reçu les résultats d'outils. "
        "Si tu dois appeler un outil, fais-le DIRECTEMENT sans annoncer ce que tu vas faire. "
        "Ta première phrase doit contenir la réponse, pas une annonce.\n"
        "INTERDIT :\n"
        "- Annoncer ce que tu vas faire ('Je vais chercher...', 'Je dois exécuter...', 'Laissez-moi...')\n"
        "- Les phrases d'intro ('Voici les résultats...', 'Basé sur les données...', 'D'après Odoo...')\n"
        "- Les commentaires d'observation non demandés ('Observations clés', 'Points notables')\n"
        "- Les propositions de suivi ('Voulez-vous approfondir...', 'Souhaitez-vous...')\n"
        "- Les répétitions de la question dans la réponse\n"
        "- Les emojis\n"
        "Commence DIRECTEMENT par le résultat. Pas un mot avant les données. "
        "Si on demande un nombre → donne uniquement le nombre + unité. "
        "Si on demande une liste → donne directement la liste. "
        "Tu peux ajouter UNE courte précision factuelle si elle est indispensable (ex: la période couverte). "
        "Langue : français uniquement.\n\n"

        "VISUALISATION — GRAPHIQUES :\n"
        "Quand la réponse contient une SÉRIE de valeurs comparables (évolution dans le temps, classement, "
        "répartition, comparaison entre entités), AJOUTE un graphique EN PLUS du texte via un bloc de code "
        "```chart contenant du JSON. Exemple exact :\n"
        "```chart\n"
        '{"type":"bar","title":"CA par année (M XOF)","unit":"M XOF",'
        '"data":[{"label":"2023","value":1200},{"label":"2024","value":1500},{"label":"2025","value":1850}]}\n'
        "```\n"
        "Types : 'bar' (comparaison/classement), 'line' (évolution temporelle), 'pie' ou 'donut' (répartition). "
        "Règles strictes :\n"
        "- 'data' = liste d'objets {label, value} ; 'value' est un nombre BRUT, sans séparateur de milliers ni unité "
        "(mets l'unité dans 'unit', ex: \"M XOF\", \"%\").\n"
        "- Pour les grands montants, convertis en millions pour la lisibilité (1 850 000 000 XOF → value:1850, unit:\"M XOF\").\n"
        "- Maximum ~12 points de données. N'INVENTE JAMAIS de valeur : uniquement les chiffres réels issus des outils.\n"
        "- Place le bloc ```chart APRÈS la réponse chiffrée (le texte/tableau reste la source, le graphique illustre).\n"
        "- PAS de graphique pour une valeur unique, une liste non numérique ou des données non quantitatives."
    )

_CRM_TOOLS = [
    {
        "name": "rechercher_clients",
        "description": (
            "Recherche des clients dans la base de données Odoo par nom ou mot-clé. "
            "Retourne une liste de clients avec leur identifiant (client_id)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Nom ou partie du nom du client"}},
            "required": ["query"],
        },
    },
    {
        "name": "obtenir_donnees_client",
        "description": (
            "Récupère commandes et factures d'UN SEUL client précis. "
            "Accepte le nom du client (partiel ou exact) OU son client_id. "
            "Pas besoin de passer par rechercher_clients d'abord — utilise directement le nom. "
            "year est optionnel pour filtrer par année.\n"
            "ATTENTION : N'utilise PAS cet outil pour des groupes de clients (ex: 'tous les clients Orange', "
            "'les banques', 'les clients telecom'). Pour un groupe → utilise executer_analyse_sql avec LIKE. "
            "Exemple groupe : SELECT client_name, SUM(amount) FROM sale_orders "
            "WHERE lower(client_name) LIKE '%orange%' AND strftime('%Y',date_order)='2025' "
            "AND state IN('sale','done') GROUP BY client_name ORDER BY SUM(amount) DESC"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name_or_id": {"type": "string", "description": "Nom (partiel ou exact) ou identifiant du client"},
                "year": {"type": "integer", "description": "Année optionnelle (ex: 2025)"},
            },
            "required": ["client_name_or_id"],
        },
    },
    {
        "name": "rechercher_bon_de_commande",
        "description": (
            "Recherche un bon de commande par sa référence (ex: FP/2026/12576, FP/2025/12473). "
            "Retourne le détail COMPLET : client, montant total, date, état (confirmé/annulé) "
            "ET la liste de tous les articles (nom du produit, quantité, sous-total en XOF). "
            "Utilise cet outil dès qu'on demande les articles, lignes, produits ou détails d'un BC."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Référence du bon de commande (ex: FP/2025/12473)"}},
            "required": ["ref"],
        },
    },
    {
        "name": "statistiques_globales",
        "description": (
            "Retourne les statistiques commerciales globales d'Odoo : "
            "nombre de clients, factures, bons de commande, chiffre d'affaires. "
            "À utiliser pour les questions de type 'combien de clients', 'quel est notre CA', "
            "'nombre de factures'. NE PAS utiliser pour les questions sur les documents GED."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"year": {"type": "integer", "description": "Année optionnelle"}},
        },
    },
    {
        "name": "requete_analytique",
        "description": (
            "Exécute une requête analytique sur les données Odoo sans cibler un client précis. "
            "Opérations disponibles : "
            "'dernieres_commandes' — les N derniers bons de commande (tous clients) ; "
            "'top_clients_ca' — les N clients avec le plus grand chiffre d'affaires ; "
            "'factures_impayees' — les N plus grosses factures non payées (triées par montant) ; "
            "'exposition_impayees' — EXPOSITION TOTALE : montant global, retard >90j, top 10 débiteurs (utilise pour 'combien on nous doit', 'exposition totale impayés', 'risque financier global') ; "
            "'stats_multi_annees' — statistiques réelles par année sur N années (clients actifs, CA, nb commandes). "
            "UTILISE 'stats_multi_annees' pour toute question du type : 'ventes sur les X dernières années', "
            "'évolution du CA', 'bilan pluriannuel', 'tendance des ventes 2022-2025'. "
            "Pour les ventes clients externes (hors transactions internes), passe exclude_internal=true. "
            "Utilise pour : 'dernier bon de commande', 'meilleurs clients', 'top clients', "
            "'factures en attente', 'qui a commandé récemment', 'classement clients'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["dernieres_commandes", "top_clients_ca", "factures_impayees", "exposition_impayees", "stats_multi_annees"],
                    "description": "Type d'analyse à effectuer",
                },
                "limit": {"type": "integer", "description": "Nombre de résultats (défaut: 5)"},
                "year": {"type": "integer", "description": "Filtrer par année (optionnel)"},
                "nb_years": {"type": "integer", "description": "Nombre d'années pour stats_multi_annees (défaut: 4, max: 6)"},
                "exclude_internal": {"type": "boolean", "description": "Si true, exclut les entités internes NEURONES (NEURONES BF, NEURONES ACADEMY, etc.) des stats"},
            },
            "required": ["operation"],
        },
    },
    {
        "name": "rechercher_documents_ged",
        "description": (
            "Recherche sémantique dans la GED (base documentaire interne) de Neurones Technologies.\n\n"

            "QUAND UTILISER :\n"
            "- Compétences, certifications ou expérience d'un ingénieur précis\n"
            "- Texte ou contenu d'une procédure interne (inclure son code si connu, ex: P-001)\n"
            "- Contenu d'une offre technique passée ou références d'un projet similaire\n"
            "- Critères ou spécifications d'un appel d'offres\n"
            "- Décisions ou actions consignées dans un PV de réunion\n"
            "- Caractéristiques techniques d'un produit (fiche technique)\n\n"

            "NE PAS UTILISER pour :\n"
            "- Données financières (CA, factures, commandes) → outils CRM\n"
            "- Compter ou lister les documents GED → utilise inventaire_ged\n"
            "- Informations non documentées (salaires, effectifs, organigramme)\n\n"

            "RÉSULTATS : passages les plus pertinents (plusieurs par document possible) avec score de pertinence (0-100). "
            "Score < 50 = résultat peu fiable, à mentionner. "
            "Si l'information cherchée n'apparaît pas dans les extraits, dis-le explicitement — "
            "ne jamais déduire ni compléter. "
            "Cite toujours le fichier source (champ 'fichier') dans ta réponse."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Mots-clés de recherche précis. "
                        "REFORMULE toujours en mots-clés — ne copie jamais la question de l'utilisateur. "
                        "Exemples par type de document :\n"
                        "• CV : 'Jean Dupont certifications AWS DevOps' ou 'ingénieur Kubernetes 5 ans expérience'\n"
                        "• Procédure : 'procédure onboarding nouveau client' ou 'procédure gestion incident réseau'\n"
                        "• Offre : 'offre technique SONABEL infrastructure réseau 2024 gagnée'\n"
                        "• PV : 'décision budget projet Cloud novembre 2024'\n"
                        "• Fiche : 'fiche technique switch Cisco référence SG-350'"
                    ),
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "inventaire_ged",
        "description": (
            "Retourne l'inventaire EXHAUSTIF de la base documentaire GED : le nombre total de "
            "documents indexés et leur répartition par type (CV, ABE, offre technique, etc.). "
            "C'est la SEULE source fiable pour répondre à : 'combien de documents en GED', "
            "'quels types de documents', 'répartition de la GED', 'la GED est-elle complète'. "
            "N'utilise PAS rechercher_documents_ged pour ces questions (qui ne voit qu'un sous-ensemble)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "rechercher_commandes_par_produit",
        "description": (
            "Cherche tous les bons de commande contenant un produit ou service précis. "
            "Retourne les commandes avec les lignes correspondantes (client, montant, articles matchés). "
            "Utilise pour : 'qui a commandé Microsoft 365', 'quels clients ont acheté le produit X', "
            "'commandes contenant Cisco', 'qui a pris une licence Y', 'clients ayant acheté [produit]'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_query": {"type": "string", "description": "Nom ou partie du nom du produit/service"},
                "year": {"type": "integer", "description": "Filtrer par année (optionnel)"},
            },
            "required": ["product_query"],
        },
    },
    {
        "name": "analyse_ca_par_produit",
        "description": (
            "Agrège le chiffre d'affaires par produit/service sur toutes les commandes. "
            "Retourne un classement : produit → CA total en XOF, nb commandes, quantité totale. "
            "Utilise pour : 'quel est notre produit le plus vendu', 'CA par produit en 2025', "
            "'analyse du portefeuille produits', 'quels produits génèrent le plus de revenus', "
            "'top produits par chiffre d'affaires'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Filtrer par année (optionnel)"},
                "limit": {"type": "integer", "description": "Nombre de produits à retourner (défaut: 20, max: 50)"},
            },
        },
    },
    {
        "name": "analyser_pipeline_commercial",
        "description": (
            "Analyse le pipeline de vente (opportunités CRM Odoo) : CA potentiel total, pondéré par probabilité, "
            "répartition par stade de vente, performance par commercial. "
            "Utilise pour : 'quel est notre pipeline commercial ?', 'combien avons-nous d'opportunités ?', "
            "'leads les plus chauds', 'quelles opportunités ont la plus forte probabilité ?', "
            "'forecast du pipeline', 'CA potentiel en cours'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["stats_pipeline", "leads_chauds"],
                    "description": "'stats_pipeline' pour vue globale, 'leads_chauds' pour le top des opportunités à fort potentiel",
                },
                "limit": {"type": "integer", "description": "Nombre de leads pour 'leads_chauds' (défaut: 10)"},
            },
        },
    },
    {
        "name": "analyse_performance_commerciaux",
        "description": (
            "Analyse les performances des commerciaux/vendeurs : CA généré, nombre de commandes, "
            "clients distincts, panier moyen. Optionnellement filtré par année et/ou trimestre. "
            "Utilise pour : 'quel commercial a le meilleur CA ?', 'classement des vendeurs', "
            "'performance des commerciaux ce trimestre', 'qui vend le plus ?', "
            "'bilan des commerciaux en 2025'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Filtrer par année (ex: 2025)"},
                "quarter": {"type": "integer", "description": "Trimestre (1, 2, 3 ou 4)"},
            },
        },
    },
    {
        "name": "evaluer_risque_clients",
        "description": (
            "Calcule un score de risque financier pour les clients (0=faible, 100=critique). "
            "Score composite basé sur : retard de paiement moyen, taux d'impayés, inactivité commerciale. "
            "Utilise pour : 'quels clients risquent de ne pas payer ?', 'clients à risque élevé', "
            "'analyse de solvabilité', 'risque de recouvrement', 'clients qui paient en retard', "
            "'prioriser les relances'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name_or_id": {"type": "string", "description": "Nom ou ID d'un client spécifique (optionnel — si absent, analyse tous les clients)"},
                "limit": {"type": "integer", "description": "Nombre de clients à afficher (défaut: 15)"},
            },
        },
    },
    {
        "name": "prevoir_chiffre_affaires",
        "description": (
            "Prévision du chiffre d'affaires de fin de trimestre basée sur la tendance des mois récents. "
            "Retourne 3 scénarios (optimiste, réaliste, pessimiste) avec le réalisé à ce jour. "
            "Utilise pour : 'quel sera notre CA à fin de trimestre ?', 'projection de revenus', "
            "'on est en bonne voie ce trimestre ?', 'prévision de ventes', "
            "'objectifs du trimestre atteignables ?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Année de la prévision (défaut: année courante)"},
            },
        },
    },
    {
        "name": "analyser_secteurs_clients",
        "description": (
            "Agrège le chiffre d'affaires par secteur d'activité des clients. "
            "Retourne : secteur, CA total, nb clients, nb commandes, panier moyen par client. "
            "Utilise pour : 'quels secteurs génèrent le plus de CA ?', 'quelle industrie est la plus rentable ?', "
            "'répartition sectorielle de nos ventes', 'marchés les plus actifs chez nous', "
            "'concentration sectorielle'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Filtrer par année (optionnel)"},
                "limit": {"type": "integer", "description": "Nombre de secteurs (défaut: 15)"},
            },
        },
    },
    {
        "name": "analyser_evolution_clients",
        "description": (
            "Analyse l'évolution du portefeuille clients entre deux années : rétention, churn (clients perdus), "
            "nouveaux clients, clients inactifs. "
            "Opérations disponibles :\n"
            "- 'retention' : taux de rétention (% clients de N-1 qui ont recommandé en N) + liste clients retenus\n"
            "- 'churn' : clients perdus (actifs en N-1 mais aucune commande en N) + liste nommée\n"
            "- 'nouveaux_clients' : clients ayant passé leur 1ère commande en N (absents de N-1)\n"
            "- 'inactifs' : clients n'ayant pas commandé depuis plus de N mois\n"
            "Utilise pour : 'taux de rétention client', 'combien de clients nous ont quittés', "
            "'clients perdus cette année', 'nouveaux clients en 2025', 'clients inactifs depuis 6 mois', "
            "'attrition clientèle', 'fidélisation clients'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["retention", "churn", "nouveaux_clients", "inactifs"],
                    "description": "Type d'analyse : 'retention', 'churn', 'nouveaux_clients' ou 'inactifs'",
                },
                "year": {"type": "integer", "description": "Année cible (défaut: année courante). Pour 'retention'/'churn'/'nouveaux_clients', compare year-1 et year."},
                "mois_inactivite": {"type": "integer", "description": "Pour 'inactifs' : nombre de mois sans commande (défaut: 6)"},
            },
            "required": ["operation"],
        },
    },
    {
        "name": "obtenir_dossier",
        "description": (
            "Récupère le détail complet d'un dossier commercial : CA provisoire/définitif, "
            "dépenses, marges (provisoire et définitive en valeur et en %), encaissements, "
            "backlog, fournisseurs payés/restants. "
            "Accepte soit la référence dossier (DC/YYYY/XXXX) soit la référence BDC (FP/YYYY/XXXX). "
            "Utilise pour : 'quelle est la marge du dossier DC/2026/0154', "
            "'donne-moi les données financières du FP/2026/12977', "
            "'montre le dossier de VERSUS BANK mai 2026', 'marge de cette commande'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Référence dossier (DC/YYYY/XXXX) ou BDC (FP/YYYY/XXXX)"},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "analyser_marges",
        "description": (
            "Analyse les marges commerciales depuis les dossiers Odoo. "
            "Peut retourner :\n"
            "- Les statistiques globales de marge (CA, dépenses, marges, encaissements) — operation='stats'\n"
            "- Le classement des DOSSIERS (pas des clients) les plus rentables — operation='top_dossiers'\n"
            "- Tous les dossiers d'un client spécifique — operation='par_client'\n"
            "ATTENTION : Pour 'top clients par marge cumulée', utilise executer_analyse_sql avec GROUP BY client_name sur la table dossiers.\n"
            "Utilise pour : 'quelle est notre marge globale', 'nos dossiers les plus rentables', "
            "'marge par client', 'analyse de rentabilité', 'dossiers avec meilleure marge %', "
            "'combien on a encaissé vs ce qu il reste à encaisser'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["stats", "top_dossiers", "par_client"],
                    "description": "Type d'analyse : stats globales, top dossiers rentables, ou dossiers par client",
                },
                "year": {"type": "integer", "description": "Filtrer par année (optionnel)"},
                "client_name": {"type": "string", "description": "Nom du client (pour operation=par_client)"},
                "limit": {"type": "integer", "description": "Nombre de dossiers à retourner (défaut: 10)"},
                "metric": {
                    "type": "string",
                    "enum": ["marge_provisoire", "marge_definitive", "perc_marge_provisoire", "perc_marge_definitive", "ca_provisoire"],
                    "description": "Métrique de tri pour top_dossiers (défaut: marge_provisoire)",
                },
            },
            "required": ["operation"],
        },
    },
    {
        "name": "executer_analyse_sql",
        "description": (
            "Exécute une requête SQL SELECT sur la base de données Odoo locale. "
            "UTILISE CET OUTIL pour toute question analytique non couverte par les outils spécialisés : "
            "croisements de tables, filtres complexes, calculs sur mesure, questions inédites.\n\n"
            "SCHÉMA COMPLET :\n"
            "• clients (client_id TEXT, name TEXT, sector TEXT, city TEXT, country TEXT)\n"
            "• sale_orders (order_id TEXT, name TEXT, client_id TEXT, client_name TEXT, "
            "amount REAL [XOF], currency TEXT, date_order DATETIME, "
            "state TEXT [sale|done|cancel|draft], salesperson_name TEXT, "
            "dossier_id TEXT [ref DC/YYYY/XXXX du dossier lié, NULL si sans dossier], "
            "order_lines JSON [{product, qty, subtotal}])\n"
            "• invoices (invoice_id TEXT, client_id TEXT, invoice_date DATE, due_date DATE, "
            "payment_date DATE, "
            "amount REAL [montant TOTAL de la facture en XOF — inclut les paiements partiels déjà effectués], "
            "amount_residual REAL [montant RESTANT à payer = 0 si payée, > 0 si impayée ou partielle], "
            "status TEXT [paid|pending|cancelled], "
            "invoice_name TEXT [ex: FAC/2026/00123])\n"
            "  → Pour les IMPAYÉS : WHERE status='pending'\n"
            "  → Pour le montant RÉEL dû : utiliser amount_residual (pas amount)\n"
            "  → Retard en jours : CAST(julianday('now')-julianday(due_date) AS INTEGER)\n"
            "  → Exemple impayés >90j avec montant réel :\n"
            "    SELECT c.name client, ROUND(SUM(i.amount_residual)/1e6,1) M_restant, COUNT(*) n,\n"
            "           MAX(CAST(julianday('now')-julianday(i.due_date) AS INTEGER)) retard_max\n"
            "    FROM invoices i JOIN clients c ON i.client_id=c.client_id\n"
            "    WHERE i.status='pending' AND julianday('now')-julianday(i.due_date)>90\n"
            "    GROUP BY c.name ORDER BY SUM(i.amount_residual) DESC LIMIT 10\n\n"
            "• contracts (contract_id TEXT, client_id TEXT, name TEXT, "
            "start_date DATE, end_date DATE, amount REAL, status TEXT [active|expired|draft])\n"
            "• opportunities (opp_id TEXT, client_id TEXT, client_name TEXT, name TEXT, "
            "stage TEXT, expected_revenue REAL, probability REAL [0-100], "
            "salesperson_name TEXT, deadline DATE)\n"
            "• dossiers (dossier_ref TEXT PK [ex: DC/2026/0154], client_name TEXT, "
            "project_name TEXT, salesperson TEXT, state TEXT [draft|confirmed|done|cancel], "
            "date_creation DATE, ca_provisoire REAL, ca_definitif REAL, "
            "depense_provisoire REAL, depense_definitive REAL, "
            "marge_provisoire REAL, marge_definitive REAL, "
            "perc_marge_provisoire REAL, perc_marge_definitive REAL, "
            "montant_recu REAL, reste_a_encaisser REAL, backlog REAL, "
            "fournisseurs_payes REAL, fournisseurs_restant REAL, "
            "nb_bdc INT, nb_factures_client INT, nb_factures_fournisseur INT)\n"
            "  → jointure sale_orders ↔ dossiers : sale_orders.dossier_id = dossiers.dossier_ref\n\n"
            "SYNTAXE SQLITE UTILE :\n"
            "• Filtrer annulés : WHERE state NOT IN ('cancel', 'draft')\n"
            "• Filtrer par année : strftime('%Y', date_order) = '2025'\n"
            "• Filtrer par mois : strftime('%Y-%m', date_order) = '2026-04'\n"
            "• Filtrer par trimestre : strftime('%m', date_order) BETWEEN '04' AND '06'\n"
            "• Requête sur lignes de commande JSON :\n"
            "  SELECT o.client_name, json_extract(j.value,'$.product'), json_extract(j.value,'$.subtotal')\n"
            "  FROM sale_orders o, json_each(o.order_lines) j WHERE ...\n"
            "• Jointure clients+commandes : JOIN clients c ON o.client_id = c.client_id\n"
            "• IMPORTANT — Comparer un client sur plusieurs années : utilise client_name (pas client_id)\n"
            "  car le même partenaire peut avoir plusieurs client_id dans Odoo. Exemple cross-année :\n"
            "  WITH ca24 AS (SELECT client_name, SUM(amount) ca FROM sale_orders\n"
            "    WHERE strftime('%Y',date_order)='2024' AND state IN('sale','done') GROUP BY client_name),\n"
            "  ca25 AS (SELECT client_name, SUM(amount) ca FROM sale_orders\n"
            "    WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done') GROUP BY client_name)\n"
            "  SELECT a.client_name, a.ca ca2024, b.ca ca2025,\n"
            "         ROUND((b.ca-a.ca)/a.ca*100,1) pct_growth\n"
            "  FROM ca24 a JOIN ca25 b ON a.client_name=b.client_name\n"
            "  WHERE b.ca > a.ca*1.2 ORDER BY pct_growth DESC LIMIT 20\n"
            "• BDC d'une année → dossiers associés (via dossier_id) — ex: top clients par CA dossier sur BDC 2025 :\n"
            "  SELECT d.client_name, SUM(d.ca_provisoire)/1e6 ca, AVG(d.perc_marge_provisoire) pct, COUNT(DISTINCT d.dossier_ref) nb\n"
            "  FROM sale_orders s JOIN dossiers d ON s.dossier_id = d.dossier_ref\n"
            "  WHERE strftime('%Y', s.date_order)='2025' AND s.state IN('sale','done')\n"
            "  GROUP BY d.client_name ORDER BY ca DESC LIMIT 10\n"
            "• Top clients par marge cumulée sur tous les dossiers :\n"
            "  SELECT client_name, SUM(marge_provisoire)/1e6 mg, SUM(ca_provisoire)/1e6 ca,\n"
            "         AVG(perc_marge_provisoire) pct, COUNT(*) nb\n"
            "  FROM dossiers GROUP BY client_name ORDER BY SUM(marge_provisoire) DESC LIMIT 10\n\n"
            "RÈGLES : SELECT uniquement — les modifications sont bloquées. Max 200 lignes retournées."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Requête SQL SELECT à exécuter (lecture seule, SQLite)",
                },
                "description": {
                    "type": "string",
                    "description": "Ce que cette requête calcule (pour le log)",
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "analyser_cross_sell",
        "description": (
            "Identifie les clients ayant acheté un produit/service mais pas un autre complémentaire. "
            "Outil de cross-sell et upsell : 'qui achète X mais pas Y ?'. "
            "Utilise pour : 'clients Microsoft 365 qui n'ont pas Azure', 'clients ayant pris la licence de base "
            "mais pas le support premium', 'opportunités cross-sell', 'clients sous-exploités commercialement'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produit_possede": {"type": "string", "description": "Produit/service que le client a déjà acheté"},
                "produit_cible": {"type": "string", "description": "Produit/service complémentaire qu'il n'a pas encore (optionnel)"},
                "limit": {"type": "integer", "description": "Nombre de clients à retourner (défaut: 20)"},
            },
            "required": ["produit_possede"],
        },
    },
    {
        "name": "interroger_documents",
        "description": (
            "Interroge la base DOCUMENTAIRE structurée (kb_*) en SQL SELECT (LECTURE SEULE). "
            "UTILISE CET OUTIL pour COMPTER / FILTRER / COMPARER / CROISER les documents de la GED : "
            "CV, appels d'offres (AO), attestations de bonne exécution, certifications, PV de recette, comptes rendus. "
            "À distinguer de executer_analyse_sql qui interroge les données commerciales Odoo (ventes/factures/dossiers).\n\n"
            "EXEMPLES :\n"
            "• 'combien d'attestations > 200M FCFA ces 3 dernières années' → "
            "SELECT COUNT(*) FROM kb_attestation WHERE montant_valeur>200000000 AND date_fin>=date('now','-3 years')\n"
            "• 'certifications expirant en 2026, par titulaire' → "
            "SELECT titulaire, intitule, date_expiration, doc_id, fichier_source FROM kb_certification "
            "WHERE strftime('%Y',date_expiration)='2026' ORDER BY titulaire\n"
            "• 'consultants avec la certif PMP ET une expérience secteur bancaire' → "
            "SELECT DISTINCT cv.nom_complet, cv.doc_id, cv.fichier_source FROM kb_cv cv "
            "JOIN kb_cv_certifications c ON c.doc_id=cv.doc_id "
            "JOIN kb_cv_experiences e ON e.doc_id=cv.doc_id "
            "WHERE c.intitule LIKE '%PMP%' AND e.secteur LIKE '%banc%'\n"
            "• 'pour l'AO réf X, ai-je ≥3 références conformes au montant minimum' → croiser "
            "kb_ao_references_demandees (montant_min_valeur) et kb_attestation (montant_valeur).\n\n"
            "MONTANTS : filtre sur les colonnes *_valeur (numériques). DATES : strftime('%Y',col) / date('now','-N years').\n"
            "OBLIGATOIRE : sélectionne TOUJOURS doc_id ET fichier_source pour pouvoir citer les documents sources.\n"
            "Faits fiables : possible de filtrer score_confiance ou de joindre kb_aliases (status IN ('confirmed','auto')).\n\n"
            "SCHÉMA (tables kb_* uniquement) :\n" + KB_DDL +
            "\nRÈGLES : SELECT/WITH uniquement — aucune écriture ; tables kb_* uniquement ; max 200 lignes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Requête SQL SELECT sur les tables kb_* (lecture seule, SQLite)"},
                "description": {"type": "string", "description": "Ce que cette requête calcule (pour le log)"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "obtenir_profil_complet",
        "description": (
            "Récupère le PROFIL COMPLET d'une personne à partir de son CV : le TEXTE INTÉGRAL "
            "du CV (parcours, compétences, formations) + ses expériences et certifications structurées. "
            "C'est l'outil à utiliser dès qu'on demande de DÉCRIRE / PRÉSENTER / RACONTER le profil ou "
            "le CV d'UNE personne précise — il renvoie tout le document, pas seulement un extrait.\n\n"
            "UTILISE-LE quand :\n"
            "- 'présente-moi le profil de Jean Dupont', 'décris le CV de X', 'parle-moi de Y', 'qui est Z'\n"
            "- après avoir identifié UNE personne (via rechercher_documents_ged ou interroger_documents) "
            "et que l'utilisateur veut le détail de son parcours.\n\n"
            "NE PAS l'utiliser pour COMPTER ou FILTRER des CV (→ interroger_documents), ni quand la "
            "question vise une liste de plusieurs personnes (dans ce cas, liste + résumé court, puis "
            "appelle cet outil seulement sur la personne ciblée ou à la demande).\n\n"
            "Fournis 'nom' (nom de la personne) OU 'doc_id' si tu le connais déjà. Si le nom correspond "
            "à plusieurs personnes, l'outil renvoie la liste pour que tu demandes laquelle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nom": {"type": "string", "description": "Nom (complet ou partiel) de la personne dont on veut le CV"},
                "doc_id": {"type": "string", "description": "doc_id du CV si déjà connu (prioritaire sur 'nom')"},
            },
        },
    },
]

# Labels lisibles pour les événements SSE progress
# Libellés FR des types de documents (DocumentType) pour l'inventaire GED
_GED_TYPE_LABELS = {
    "cv": "CV / certifications",
    "offre_technique": "Offres techniques",
    "abe": "Attestations de bonne exécution (ABE)",
    "pv_recette": "PV de recette",
    "procedure": "Procédures",
    "fiche_technique": "Fiches techniques",
    "compte_rendu": "Comptes-rendus",
    "ao": "Appels d'offres",
    "template": "Modèles / templates",
    "marches_similaires": "Marchés similaires",
    "unknown": "Type non classé",
}

_TOOL_LABELS = {
    "rechercher_clients": "Recherche de clients dans Odoo…",
    "obtenir_donnees_client": "Consultation des données client…",
    "rechercher_bon_de_commande": "Recherche du bon de commande…",
    "statistiques_globales": "Calcul des statistiques…",
    "requete_analytique": "Analyse des données Odoo…",
    "rechercher_documents_ged": "Recherche dans les documents GED…",
    "inventaire_ged": "Inventaire de la base documentaire GED…",
    "rechercher_commandes_par_produit": "Recherche de commandes par produit…",
    "analyse_ca_par_produit": "Analyse du CA par produit…",
    "obtenir_dossier": "Consultation du dossier commercial…",
    "analyser_marges": "Analyse des marges et de la rentabilité…",
    "analyse_performance_commerciaux": "Analyse des performances commerciales…",
    "evaluer_risque_clients": "Évaluation du risque financier clients…",
    "prevoir_chiffre_affaires": "Prévision du chiffre d'affaires…",
    "analyser_secteurs_clients": "Analyse sectorielle des ventes…",
    "analyser_cross_sell": "Analyse des opportunités cross-sell…",
    "analyser_pipeline_commercial": "Analyse du pipeline commercial…",
    "analyser_evolution_clients": "Analyse de l'évolution du portefeuille clients…",
    "executer_analyse_sql": "Analyse SQL sur mesure…",
    "interroger_documents": "Analyse SQL des documents (GED)…",
    "obtenir_profil_complet": "Récupération du profil complet…",
}


# ─── Mémoire persistante ──────────────────────────────────────────────────────

# Profils cockpit (frontend/src/lib/types.ts::PROFILE_KEYS). Une valeur inconnue
# est normalisée en "" plutôt que rejetée : le chat doit répondre même si le
# profil est absent ou farfelu, il ne sera simplement rattaché à aucune liste.
_PROFILE_KEYS = {"dg", "dc", "do", "df", "am"}


def _normalize_profile(profile: str | None) -> str:
    value = (profile or "").strip().lower()
    return value if value in _PROFILE_KEYS else ""


async def _load_history(
    session_id: str,
    user_id: int | None = None,
    profile: str | None = None,
    limit: int = 12,
) -> list[dict]:
    """Charge les N derniers tours de conversation depuis SQLite, scopés par user."""
    if not session_id:
        return []
    async with AsyncSessionLocal() as session:
        q = (
            select(ConversationModel)
            .where(ConversationModel.session_id == session_id)
        )
        if user_id is not None:
            q = q.where(ConversationModel.user_id == user_id)
        if profile:
            q = q.where(ConversationModel.profile == profile)
        q = q.order_by(ConversationModel.created_at.desc()).limit(limit)
        result = await session.execute(q)
        rows = list(reversed(result.scalars().all()))
        return [{"role": r.role, "content": r.content} for r in rows]


async def _save_turns(
    session_id: str,
    turns: list[dict],
    user_id: int | None = None,
    profile: str = "",
):
    """Sauvegarde les nouveaux tours (user + assistant) en base."""
    if not session_id or not turns:
        return
    async with AsyncSessionLocal() as session:
        for turn in turns:
            session.add(ConversationModel(
                session_id=session_id,
                user_id=user_id,
                profile=profile,
                role=turn["role"],
                content=turn["content"],
            ))
        await session.commit()


async def _cleanup_old_sessions():
    """Supprime les conversations de plus de 30 jours (lancé périodiquement)."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ConversationModel).where(ConversationModel.created_at < cutoff)
        )
        await session.commit()


# ─── Exécution des outils ─────────────────────────────────────────────────────

async def _execute_tool(tool_name: str, tool_input: dict, crm_repo, rag_engine, doc_registry=None, ro_sql=None) -> tuple[str, bool]:
    """
    Exécute un outil CRM ou GED.
    Retourne (résultat_json, is_error).
    is_error=True → Claude sait que l'outil a échoué et adapte sa stratégie.
    ro_sql : adapter SQL LECTURE SEULE (text-to-SQL Odoo + documents kb_*).
    """
    try:
        if tool_name == "rechercher_clients":
            clients = await crm_repo.search_clients(tool_input["query"])
            if not clients:
                return json.dumps({"message": "Aucun client trouvé pour cette recherche", "clients": []}, ensure_ascii=False), False
            return json.dumps({
                "clients": [{"client_id": c.client_id, "nom": c.name, "secteur": c.sector} for c in clients[:10]]
            }, ensure_ascii=False), False

        elif tool_name == "obtenir_donnees_client":
            name_or_id = tool_input.get("client_name_or_id") or tool_input.get("client_id", "")
            year = tool_input.get("year")
            client = await crm_repo.get_client(name_or_id)
            if not client:
                candidates = await crm_repo.search_clients(name_or_id)
                client = candidates[0] if candidates else None
            if not client:
                return json.dumps({"erreur": f"Client introuvable : '{name_or_id}'. Essaie rechercher_clients pour voir les noms exacts."}), True

            sale_orders = await crm_repo.get_sale_orders(client.client_id, year=year)
            invoices = await crm_repo.get_invoices(client.client_id)

            result: dict = {"client": client.name, "client_id": client.client_id}
            if year:
                result["année_filtrée"] = year
            if sale_orders:
                displayed = sale_orders[:50]
                # Strip order_lines from overview (too verbose — use rechercher_bon_de_commande for details)
                compact = [
                    {
                        "ref": o["name"],
                        "montant_xof": o["amount"],
                        "date": o["date_order"],
                        "état": o["state"],
                        "commercial": o.get("salesperson", ""),
                        "nb_articles": len(o.get("lines", [])),
                    }
                    for o in displayed
                ]
                result["bons_de_commande"] = {
                    "total": len(sale_orders),
                    "montant_total_xof": sum(o["amount"] for o in sale_orders),
                    "note": "Utilise rechercher_bon_de_commande(ref) pour voir le détail des articles d'une commande spécifique.",
                    "liste": compact,
                }
            else:
                result["bons_de_commande"] = {"total": 0, "message": "Aucune commande trouvée"}
            if invoices:
                paid = [i for i in invoices if i.status.value == "paid"]
                result["factures"] = {
                    "total": len(invoices), "payées": len(paid),
                    "en_attente": len(invoices) - len(paid),
                    "montant_total_xof": sum(i.amount for i in invoices),
                }
            else:
                result["factures"] = {"total": 0}
            return json.dumps(result, ensure_ascii=False, default=str), False

        elif tool_name == "rechercher_bon_de_commande":
            order = await crm_repo.get_order_by_ref(tool_input["ref"])
            if not order:
                return json.dumps({"erreur": f"Bon de commande '{tool_input['ref']}' non trouvé. Vérifie la référence ou utilise obtenir_donnees_client pour voir les commandes d'un client."}), True
            return json.dumps(order, ensure_ascii=False, default=str), False

        elif tool_name == "statistiques_globales":
            year = tool_input.get("year")
            if year:
                stats = await crm_repo.get_year_stats(year)
                top_orders = await crm_repo.get_recent_orders(limit=10, year=year)
                return json.dumps({
                    "année": year,
                    "clients_ayant_commandé": stats["clients_with_orders"],
                    "nombre_total_bons_de_commande": stats["orders_count"],
                    "chiffre_affaires_xof": stats["revenue_xof"],
                    "top_10_commandes_par_date_desc": top_orders,
                    "avertissement": (
                        f"Le top_10 ci-dessus représente les 10 dernières commandes de {year} uniquement. "
                        f"Il y a {stats['orders_count']} commandes au total cette année. "
                        "NE PAS inventer d'autres références — utiliser obtenir_donnees_client par client pour plus de détails."
                    ),
                }, ensure_ascii=False), False
            stats = await crm_repo.get_aggregate_stats()
            return json.dumps({
                "clients_total": stats["clients"],
                "factures_total": stats["invoices"],
                "factures_payées": stats["invoices_paid"],
                "bons_de_commande": stats["sale_orders"],
                "chiffre_affaires_total_xof": stats["total_revenue_xof"],
            }, ensure_ascii=False), False

        elif tool_name == "requete_analytique":
            op = tool_input.get("operation", "")
            limit = tool_input.get("limit", 5)
            year = tool_input.get("year")
            if op == "dernieres_commandes":
                orders = await crm_repo.get_recent_orders(limit=limit, year=year)
                return json.dumps({"dernières_commandes": orders}, ensure_ascii=False, default=str), False
            elif op == "top_clients_ca":
                clients = await crm_repo.get_top_clients(limit=limit, year=year)
                return json.dumps({"top_clients_ca": clients}, ensure_ascii=False, default=str), False
            elif op == "factures_impayees":
                invoices = await crm_repo.get_unpaid_invoices(limit=limit)
                return json.dumps({"factures_impayees": invoices}, ensure_ascii=False, default=str), False
            elif op == "exposition_impayees":
                exposure = await crm_repo.get_unpaid_exposure()
                return json.dumps({"exposition_impayees": exposure}, ensure_ascii=False, default=str), False
            elif op == "stats_multi_annees":
                from datetime import datetime as _dt
                current_year = _dt.now().year
                nb_years = min(int(tool_input.get("nb_years", 4)), 6)
                exclude_internal = bool(tool_input.get("exclude_internal", False))
                years = list(range(current_year - nb_years + 1, current_year + 1))
                results = []
                for y in years:
                    s = await crm_repo.get_year_stats(y, exclude_internal=exclude_internal)
                    results.append({
                        "année": y,
                        "clients_actifs": s["clients_with_orders"],
                        "nombre_commandes": s["orders_count"],
                        "chiffre_affaires_xof": s["revenue_xof"],
                    })
                scope = "hors entités internes NEURONES" if exclude_internal else "toutes entités incluses (inter-groupe compris)"
                return json.dumps({
                    "périmètre": scope,
                    "statistiques_par_année": results,
                    "avertissement": (
                        "Ces statistiques sont issues directement de la base Odoo (counts et sums réels). "
                        "NE PAS inventer de références de commandes à partir de ces chiffres."
                    ),
                }, ensure_ascii=False), False
            return json.dumps({"erreur": f"Opération inconnue : {op}"}), True

        elif tool_name == "rechercher_commandes_par_produit":
            product_query = tool_input.get("product_query", "")
            year = tool_input.get("year")
            orders = await crm_repo.search_orders_by_product(product_query, year)
            if not orders:
                return json.dumps({"message": f"Aucune commande trouvée contenant '{product_query}'"}, ensure_ascii=False), False
            return json.dumps({
                "produit_recherché": product_query,
                "filtre_année": year,
                "total_commandes_trouvées": len(orders),
                "commandes": orders,
            }, ensure_ascii=False, default=str), False

        elif tool_name == "analyse_ca_par_produit":
            year = tool_input.get("year")
            limit = min(int(tool_input.get("limit", 20)), 50)
            data = await crm_repo.get_revenue_by_product(year=year, limit=limit)
            if not data:
                return json.dumps({"message": "Aucune donnée de CA par produit disponible."}), False
            return json.dumps({
                "filtre_année": year or "toutes années",
                "nb_produits_distincts": len(data),
                "classement_par_ca": data,
                "avertissement": "Classement basé sur les sous-totaux des lignes de commande Odoo (hors lignes à 0 XOF).",
            }, ensure_ascii=False), False

        elif tool_name == "obtenir_dossier":
            ref = tool_input.get("ref", "")
            dossier = await crm_repo.get_dossier(ref)
            if not dossier:
                return json.dumps({"erreur": f"Dossier introuvable pour la référence '{ref}'."}), True
            return json.dumps(dossier, ensure_ascii=False, default=str), False

        elif tool_name == "analyser_marges":
            op = tool_input.get("operation", "stats")
            year = tool_input.get("year")
            limit = min(int(tool_input.get("limit", 10)), 50)
            if op == "stats":
                data = await crm_repo.get_margin_stats(year=year)
                return json.dumps(data, ensure_ascii=False, default=str), False
            elif op == "top_dossiers":
                metric = tool_input.get("metric", "marge_provisoire")
                data = await crm_repo.get_top_margin_dossiers(limit=limit, year=year, metric=metric)
                return json.dumps({
                    "critere": metric, "annee": year or "toutes",
                    "top_dossiers": data,
                }, ensure_ascii=False, default=str), False
            elif op == "par_client":
                client_name = tool_input.get("client_name", "")
                if not client_name:
                    return json.dumps({"erreur": "client_name requis pour operation=par_client"}), True
                data = await crm_repo.get_dossiers_by_client(client_name, year=year)
                return json.dumps({
                    "client_recherché": client_name, "annee": year or "toutes",
                    "nb_dossiers": len(data), "dossiers": data,
                }, ensure_ascii=False, default=str), False
            return json.dumps({"erreur": f"Operation inconnue : {op}"}), True

        elif tool_name == "analyser_pipeline_commercial":
            op = tool_input.get("operation", "stats_pipeline")
            if op == "leads_chauds":
                limit = min(int(tool_input.get("limit", 10)), 30)
                leads = await crm_repo.get_hot_leads(limit=limit)
                if not leads:
                    return json.dumps({"message": "Aucune opportunité dans le pipeline (sync crm.lead requise)."}), False
                return json.dumps({
                    "top_opportunites": leads,
                    "note": "Score pondéré = revenu_attendu × probabilité%. Plus le score est élevé, plus l'opportunité est prioritaire.",
                }, ensure_ascii=False, default=str), False
            else:
                stats = await crm_repo.get_pipeline_stats()
                if not stats or stats.get("total_opportunités", 0) == 0:
                    return json.dumps({"message": "Pipeline vide ou non synchronisé depuis Odoo (crm.lead non synced encore)."}), False
                return json.dumps(stats, ensure_ascii=False), False

        elif tool_name == "analyse_performance_commerciaux":
            year = tool_input.get("year")
            quarter = tool_input.get("quarter")
            data = await crm_repo.get_revenue_by_salesperson(year=year, quarter=quarter)
            if not data:
                return json.dumps({"message": "Aucune donnée de performance commerciale disponible."}), False
            period = f"Q{quarter} " if quarter else ""
            period += str(year) if year else "toutes périodes"
            return json.dumps({
                "période": period,
                "nb_commerciaux": len(data),
                "classement_commerciaux": data,
                "note": "CA brut uniquement — données de marge non encore disponibles (nécessite sync coût produits Odoo).",
            }, ensure_ascii=False), False

        elif tool_name == "evaluer_risque_clients":
            client_name_or_id = tool_input.get("client_name_or_id", "")
            limit = min(int(tool_input.get("limit", 15)), 50)
            if client_name_or_id:
                client = await crm_repo.get_client(client_name_or_id)
                client_id = client.client_id if client else client_name_or_id
            else:
                client_id = None
            data = await crm_repo.score_client_risk(client_id=client_id, limit=limit)
            if not data:
                return json.dumps({"message": "Aucune donnée de risque client disponible."}), False
            high_risk = [c for c in data if c["score_risque"] >= 60]
            return json.dumps({
                "clients_analysés": len(data),
                "clients_risque_élevé": len(high_risk),
                "classement_par_risque": data,
                "légende_score": "0-29: FAIBLE | 30-59: MODÉRÉ | 60-100: ÉLEVÉ",
            }, ensure_ascii=False, default=str), False

        elif tool_name == "prevoir_chiffre_affaires":
            year = tool_input.get("year")
            forecast = await crm_repo.get_quarterly_forecast(year=year)
            if not forecast:
                return json.dumps({"message": "Données insuffisantes pour une prévision."}), False
            return json.dumps(forecast, ensure_ascii=False), False

        elif tool_name == "analyser_secteurs_clients":
            year = tool_input.get("year")
            limit = min(int(tool_input.get("limit", 15)), 30)
            data = await crm_repo.get_revenue_by_sector(year=year, limit=limit)
            if not data:
                return json.dumps({"message": "Aucune donnée sectorielle disponible."}), False
            return json.dumps({
                "filtre_année": year or "toutes années",
                "nb_secteurs": len(data),
                "répartition_sectorielle": data,
            }, ensure_ascii=False), False

        elif tool_name in ("executer_analyse_sql", "interroger_documents"):
            # text-to-SQL borné, LECTURE SEULE (mode=ro + query_only) avec garde-fou
            # applicatif (SELECT-only, liste blanche de tables, anti-injection).
            if ro_sql is None:
                return json.dumps({"erreur": "Moteur SQL en lecture seule indisponible."}), True
            raw_sql = tool_input.get("sql", "")
            desc = tool_input.get("description", "requête SQL")
            allowed = KB_TABLES if tool_name == "interroger_documents" else ODOO_TABLES
            note = ("Max 200 lignes. Cite doc_id + fichier_source dans ta réponse."
                    if tool_name == "interroger_documents"
                    else "Max 200 lignes. Affine avec WHERE ou LIMIT si nécessaire.")
            try:
                res = await ro_sql.query(raw_sql, allowed)
            except SqlGuardError as guard_err:
                return json.dumps({"erreur": f"Requête refusée (garde-fou) : {guard_err}"}), True
            except asyncio.TimeoutError:
                return json.dumps({"erreur": "Requête trop longue (timeout). Ajoute des filtres ou un LIMIT."}), True
            except Exception as sql_err:
                return json.dumps({"erreur": f"Erreur SQL : {sql_err}. Corrige la requête et réessaie."}), True
            return json.dumps({
                "description": desc,
                "colonnes": res["colonnes"],
                "nb_lignes_retournees": res["nb_lignes"],
                "resultats": res["resultats"],
                "note": note,
            }, ensure_ascii=False), False

        elif tool_name == "analyser_evolution_clients":
            from datetime import datetime as _dt
            op = tool_input.get("operation", "retention")
            year = tool_input.get("year") or _dt.now().year

            if op in ("retention", "churn", "nouveaux_clients"):
                data = await crm_repo.get_client_retention(year=year)
                if not data:
                    return json.dumps({"message": "Données insuffisantes pour calculer la rétention."}), False
                if op == "retention":
                    return json.dumps({
                        "période": f"{data['annee_reference']} → {data['annee_cible']}",
                        "clients_actifs_N_moins_1": data["clients_actifs_annee_ref"],
                        "clients_actifs_N": data["clients_actifs_annee_cible"],
                        "clients_retenus": data["clients_retenus"],
                        "taux_retention_pct": data["taux_retention_pct"],
                        "note": data["note"],
                    }, ensure_ascii=False), False
                elif op == "churn":
                    return json.dumps({
                        "période": f"{data['annee_reference']} → {data['annee_cible']}",
                        "clients_perdus": data["clients_perdus_churn"],
                        "taux_churn_pct": data["taux_churn_pct"],
                        "liste_clients_perdus_30_premiers": data["liste_clients_perdus"],
                        "note": data["note"],
                    }, ensure_ascii=False), False
                else:  # nouveaux_clients
                    return json.dumps({
                        "année": data["annee_cible"],
                        "nouveaux_clients": data["nouveaux_clients"],
                        "liste_nouveaux_30_premiers": data["liste_nouveaux_clients"],
                        "note": data["note"],
                    }, ensure_ascii=False), False

            elif op == "inactifs":
                from sqlalchemy import text
                mois = int(tool_input.get("mois_inactivite", 6))
                sql = """
                    SELECT c.name, MAX(o.date_order) as derniere_commande,
                           COUNT(o.order_id) as nb_commandes,
                           SUM(o.amount) as ca_total
                    FROM clients c
                    JOIN sale_orders o ON c.client_id = o.client_id
                    WHERE o.state NOT IN ('cancel', 'draft')
                    GROUP BY c.client_id, c.name
                    HAVING derniere_commande < date('now', :seuil)
                    ORDER BY derniere_commande DESC
                    LIMIT 30
                """
                from db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db_session:
                    rows = (await db_session.execute(
                        text(sql), {"seuil": f"-{mois} months"}
                    )).fetchall()
                return json.dumps({
                    "seuil_inactivite_mois": mois,
                    "nb_clients_inactifs": len(rows),
                    "clients_inactifs": [
                        {
                            "client": r[0],
                            "derniere_commande": str(r[1]),
                            "nb_commandes_historique": r[2],
                            "ca_historique_xof": round(r[3] or 0),
                        }
                        for r in rows
                    ],
                }, ensure_ascii=False), False

            return json.dumps({"erreur": f"Opération inconnue : {op}"}), True

        elif tool_name == "analyser_cross_sell":
            product_anchor = tool_input.get("produit_possede", "")
            product_target = tool_input.get("produit_cible")
            limit = min(int(tool_input.get("limit", 20)), 50)
            if not product_anchor:
                return json.dumps({"erreur": "Le paramètre 'produit_possede' est requis."}), True
            data = await crm_repo.get_cross_sell_opportunities(product_anchor, product_target, limit)
            if not data:
                msg = f"Aucun client trouvé ayant acheté '{product_anchor}'"
                msg += f" mais pas '{product_target}'" if product_target else ""
                return json.dumps({"message": msg}), False
            return json.dumps({
                "produit_ancre": product_anchor,
                "produit_cible": product_target or "tout produit complémentaire",
                "nb_opportunites": len(data),
                "clients_à_cibler": data,
            }, ensure_ascii=False, default=str), False

        elif tool_name == "inventaire_ged":
            try:
                inv = await rag_engine.inventory()
                par_type = {
                    _GED_TYPE_LABELS.get(t, t): n for t, n in inv["par_type"].items()
                }
                return json.dumps({
                    "total_documents": inv["total_documents"],
                    "total_chunks_indexes": inv["total_chunks"],
                    "repartition_par_type": par_type,
                    "note": (
                        "Inventaire exhaustif et exact de la GED. Utilise total_documents comme "
                        "nombre total de documents."
                    ),
                }, ensure_ascii=False), False
            except Exception as e:
                return json.dumps({"erreur": f"Inventaire GED indisponible : {e}."}), True

        elif tool_name == "rechercher_documents_ged":
            try:
                sources = await rag_engine.search(
                    tool_input["query"],
                    min_dense_score=settings.ged_min_similarity,
                )
                # Total exhaustif pour éviter que le LLM prenne ce top-k pour toute la GED.
                try:
                    total_ged = (await rag_engine.inventory())["total_documents"]
                except Exception:
                    total_ged = None
                if not sources:
                    return json.dumps({
                        "message": "Aucun document trouvé dans la GED pour cette recherche.",
                        "documents": [],
                        "total_documents_ged": total_ged,
                    }, ensure_ascii=False), False
                return json.dumps({
                    "documents": [
                        {
                            "fichier": s.filename,
                            "type": s.doc_type.value,
                            "extrait": (s.content or s.excerpt)[:1200],
                            "pertinence": round(s.relevance_score * 100),
                        }
                        for s in sources
                    ],
                    "total_documents_ged": total_ged,
                    "avertissement": (
                        "Ces documents sont seulement les plus pertinents pour la recherche, "
                        "PAS la liste complète de la GED. Pour le nombre total ou un inventaire, "
                        "utilise l'outil inventaire_ged."
                    ),
                }, ensure_ascii=False), False
            except Exception as e:
                return json.dumps({"erreur": f"GED indisponible : {e}. Essaie un autre outil."}), True

        elif tool_name == "obtenir_profil_complet":
            # Profil COMPLET d'une personne : texte intégral du CV (tous les chunks)
            # + structuré (kb_cv / expériences / certifications). Sert à raconter
            # toute l'histoire de la personne, pas seulement le fragment recherché.
            if ro_sql is None:
                return json.dumps({"erreur": "Moteur SQL en lecture seule indisponible."}), True
            doc_id = (tool_input.get("doc_id") or "").strip()
            nom = (tool_input.get("nom") or "").strip()
            if not doc_id and not nom:
                return json.dumps({"erreur": "Fournis 'nom' ou 'doc_id'."}), True
            try:
                # 1. Résolution du doc_id à partir du nom si nécessaire.
                if not doc_id:
                    esc = nom.replace("'", "''")
                    res = await ro_sql.query(
                        "SELECT doc_id, nom_complet, fichier_source FROM kb_cv "
                        f"WHERE nom_complet LIKE '%{esc}%' LIMIT 20",
                        KB_TABLES,
                    )
                    rows = res["resultats"]
                    uniq = {r["doc_id"]: r for r in rows}
                    if not uniq:
                        return json.dumps({
                            "message": f"Aucun CV trouvé pour '{nom}' dans la GED.",
                            "profil": None,
                        }, ensure_ascii=False), False
                    if len(uniq) > 1:
                        return json.dumps({
                            "message": (
                                f"Plusieurs personnes correspondent à '{nom}'. "
                                "Demande à l'utilisateur de préciser, ou rappelle cet outil avec le doc_id voulu."
                            ),
                            "candidats": [
                                {"nom": r.get("nom_complet"), "doc_id": d, "fichier_source": r.get("fichier_source")}
                                for d, r in uniq.items()
                            ],
                        }, ensure_ascii=False), False
                    doc_id = next(iter(uniq))

                esc_id = doc_id.replace("'", "''")
                # 2. Texte intégral reconstruit depuis tous les chunks.
                full = await rag_engine.get_full_document(doc_id)
                texte = (full or {}).get("texte_integral", "") or ""
                MAX_CHARS = 14_000
                tronque = len(texte) > MAX_CHARS
                if tronque:
                    texte = texte[:MAX_CHARS]

                # 3. Fiche structurée (identité + expériences + certifications).
                cv_res = await ro_sql.query(
                    "SELECT nom_complet, titre_poste, annees_experience, localisation, fichier_source "
                    f"FROM kb_cv WHERE doc_id='{esc_id}' LIMIT 1",
                    KB_TABLES,
                )
                cv_row = cv_res["resultats"][0] if cv_res["resultats"] else {}
                exp_res = await ro_sql.query(
                    "SELECT intitule_projet, client, role, secteur, date_debut, date_fin, en_cours "
                    f"FROM kb_cv_experiences WHERE doc_id='{esc_id}' "
                    "ORDER BY date_debut DESC LIMIT 100",
                    KB_TABLES,
                )
                cert_res = await ro_sql.query(
                    "SELECT intitule, organisme, annee "
                    f"FROM kb_cv_certifications WHERE doc_id='{esc_id}' ORDER BY annee DESC LIMIT 100",
                    KB_TABLES,
                )

                if not texte and not cv_row:
                    return json.dumps({
                        "message": f"Aucun contenu trouvé pour le doc_id '{doc_id}'.",
                        "profil": None,
                    }, ensure_ascii=False), False

                return json.dumps({
                    "profil": {
                        "doc_id": doc_id,
                        "nom": cv_row.get("nom_complet"),
                        "titre": cv_row.get("titre_poste"),
                        "annees_experience": cv_row.get("annees_experience"),
                        "localisation": cv_row.get("localisation"),
                        "fichier_source": cv_row.get("fichier_source") or (full or {}).get("filename"),
                        "experiences": exp_res["resultats"],
                        "certifications": cert_res["resultats"],
                        "texte_integral": texte,
                        "texte_tronque": tronque,
                    },
                    "consigne": (
                        "Raconte l'HISTOIRE COMPLÈTE de la personne à partir de ces données : synthèse du profil, "
                        "parcours et expériences (du plus récent au plus ancien), formations, certifications et "
                        "compétences clés. Appuie-toi sur 'texte_integral' pour le détail narratif et sur les listes "
                        "structurées pour la précision. Cite le fichier source."
                    ),
                }, ensure_ascii=False), False
            except SqlGuardError as guard_err:
                return json.dumps({"erreur": f"Requête refusée (garde-fou) : {guard_err}"}), True
            except Exception as e:
                return json.dumps({"erreur": f"Profil indisponible : {e}. Essaie rechercher_documents_ged."}), True

        return json.dumps({"erreur": f"Outil inconnu : {tool_name}"}), True

    except Exception as exc:
        logger.error("Tool %s error: %s", tool_name, exc)
        return json.dumps({"erreur": str(exc)}), True


# ─── Endpoint principal ───────────────────────────────────────────────────────

@router.post("/query")
async def chat_query(
    request: Request,
    current_user: CurrentUser,
    text: str = Form(...),
    session_id: str = Form(""),
    history: str = Form("[]"),
    profile: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """
    Chat IA interne — SSE streaming avec :
    - Mémoire persistante par session
    - 6 outils CRM+GED
    - Pièces jointes (PDF, Word, TXT) analysées et injectées dans le contexte
    - Progress streaming (tool_call events)
    """
    container = request.app.state.container
    crm_repo = container.crm_repo
    # Chat (uc02) : moteur RAG FR (CamemBERT) sur la collection neurones_ged_fr.
    # Presale (uc10) garde container.rag_engine (collection historique) — non impacté.
    rag_engine = container.rag_engine_fr
    llm = container.llm_haiku

    # Parser les fichiers joints AVANT de démarrer le streaming
    parsed_docs = await _parse_uploaded_files(files, container.pdf_parser, container.docx_parser)
    history_data = json.loads(history) if history else []
    profile_val = _normalize_profile(profile)

    async def event_stream() -> AsyncIterator[str]:
        import traceback
        try:
            session_id_val = session_id or ""

            # ── 1. Charger la mémoire persistante ──────────────────────────
            if session_id_val:
                db_history = await _load_history(
                    session_id_val, user_id=current_user.id, profile=profile_val
                )
                if db_history and not history_data:
                    messages = db_history.copy()
                elif history_data:
                    messages = [{"role": t["role"], "content": t["content"]} for t in history_data[-6:]]
                else:
                    messages = []
            else:
                messages = [{"role": t["role"], "content": t["content"]} for t in history_data[-6:]]

            # ── Injecter les documents joints dans le message utilisateur ──
            user_content = text
            if parsed_docs:
                doc_blocks = [f"=== {d['filename']} ===\n{d['content']}" for d in parsed_docs]
                user_content = (
                    f"{text}\n\n---\n## Document(s) joint(s) :\n" + "\n\n".join(doc_blocks)
                )
            messages.append({"role": "user", "content": user_content})

            # ── 2. Intent rapide (~0ms) ──────────────────────────────────────
            intent_hint = _classify_intent_rules(text)
            if intent_hint is None and _RE_CLIENT_QUERY.search(text):
                intent_hint = "local_db"

            # ── 3. RAG + Pre-fetch CRM en PARALLÈLE ─────────────────────────
            async def _do_rag() -> tuple[list, str]:
                if intent_hint == "local_db" or parsed_docs:
                    return [], ""
                try:
                    srcs = await rag_engine.search(text, min_dense_score=settings.ged_min_similarity)
                    ctx = await rag_engine.build_context(srcs, max_tokens=settings.max_context_tokens) if srcs else ""
                    return srcs, ctx
                except Exception as e:
                    logger.warning("RAG indisponible: %s", e)
                    return [], ""

            async def _do_prefetch() -> str:
                if intent_hint not in ("local_db", None) or parsed_docs:
                    return ""
                try:
                    # ── Référence BC dans le message ou dans l'historique récent ──────
                    ref_in_msg = _RE_ORDER_REF.search(text)
                    ref_str = ref_in_msg.group(0).upper() if ref_in_msg else None
                    if not ref_str and _RE_ARTICLES_QUERY.search(text):
                        # Chercher une référence BC dans les 6 derniers messages de l'historique
                        for msg in reversed(messages[:-1]):
                            found = _RE_ORDER_REF.search(str(msg.get("content", "")))
                            if found:
                                ref_str = found.group(0).upper()
                                break
                    if ref_str:
                        order = await crm_repo.get_order_by_ref(ref_str)
                        if order:
                            lines_txt = ""
                            if order.get("lines"):
                                items = [
                                    f"  • {l['product']} | Qté : {l['qty']:g} | {l['subtotal']:,.0f} XOF"
                                    for l in order["lines"] if l.get("product")
                                ]
                                lines_txt = "\nArticles :\n" + "\n".join(items) if items else "\n(Aucun article détaillé)"
                            invoices_txt = ""
                            if order.get("invoices"):
                                items_i = [
                                    f"  • {i['name']} | {i['amount']:,.0f} {order['currency']} | {i.get('status', '—')}"
                                    for i in order["invoices"] if i.get("name")
                                ]
                                invoices_txt = "\nFactures liées :\n" + "\n".join(items_i) if items_i else ""
                            return (
                                f"Bon de commande {ref_str} :\n"
                                f"- Client : {order['client_name']}\n"
                                f"- Montant : {order['amount']:,.0f} {order['currency']}\n"
                                f"- Date : {order['date_order']}\n"
                                f"- État : {order['state']}\n"
                                f"- Commercial : {order.get('salesperson', '—')}"
                                + lines_txt
                                + invoices_txt
                            )
                        else:
                            return f"Le bon de commande {ref_str} est introuvable dans la base Odoo."

                    if _RE_RECENT_ORDERS.search(text):
                        orders = await crm_repo.get_recent_orders(limit=10)
                        return f"Voici les dernières commandes clients :\n{json.dumps(orders, ensure_ascii=False, default=str)}"
                    elif _RE_TOP_CLIENTS.search(text):
                        _year_m = re.search(r'\b(20\d\d)\b', text)
                        _year = int(_year_m.group(1)) if _year_m else None
                        clients = await crm_repo.get_top_clients(limit=10, year=_year)
                        _lbl = f"Top clients par CA {_year or '(toutes années)'} :"
                        return f"{_lbl}\n{json.dumps(clients, ensure_ascii=False, default=str)}"
                    elif _RE_UNPAID.search(text):
                        exposure = await crm_repo.get_unpaid_exposure()
                        top_detail = await crm_repo.get_unpaid_invoices(limit=10)
                        return (
                            f"Exposition totale aux impayés :\n{json.dumps(exposure, ensure_ascii=False, default=str)}\n"
                            f"Détail top 10 factures (par montant) :\n{json.dumps(top_detail, ensure_ascii=False, default=str)}"
                        )
                    elif _RE_GLOBAL_STATS.search(text):
                        # Si une année est mentionnée, retourner les stats annuelles (pas globales)
                        _yr_m = re.search(r'\b(20\d\d)\b', text)
                        if _yr_m:
                            _yr = int(_yr_m.group(1))
                            yr_stats = await crm_repo.get_year_stats(_yr)
                            return f"Statistiques {_yr} :\n{json.dumps(yr_stats, ensure_ascii=False, default=str)}"
                        stats = await crm_repo.get_aggregate_stats()
                        return f"Statistiques globales Odoo :\n{json.dumps(stats, ensure_ascii=False, default=str)}"
                    else:
                        m = _RE_CLIENT_QUERY.search(text)
                        if m:
                            raw_name = m.group(1).strip().rstrip(".,;?!").strip()
                            stopwords = {"BONJOUR", "FRANCE", "LINUX", "WINDOWS", "OCTOBRE",
                                         "JANVIER", "FEVRIER", "MARS", "AVRIL", "JUIN",
                                         "JUILLET", "AOUT", "SEPTEMBRE", "NOVEMBRE", "DECEMBRE"}
                            if len(raw_name) >= 2 and raw_name.upper() not in stopwords:
                                client = await crm_repo.get_client(raw_name)
                                if not client:
                                    candidates = await crm_repo.search_clients(raw_name)
                                    client = candidates[0] if candidates else None
                                if client:
                                    sale_orders, invoices = await asyncio.gather(
                                        crm_repo.get_sale_orders(client.client_id),
                                        crm_repo.get_invoices(client.client_id),
                                    )
                                    paid = [i for i in invoices if i.status.value == "paid"]
                                    client_data = {
                                        "client": client.name, "client_id": client.client_id,
                                        "bons_de_commande": {
                                            "total": len(sale_orders),
                                            "montant_total_xof": sum(o["amount"] for o in sale_orders),
                                            "détail": sale_orders[:10],
                                        } if sale_orders else {"total": 0},
                                        "factures": {
                                            "total": len(invoices), "payées": len(paid),
                                            "en_attente": len(invoices) - len(paid),
                                            "montant_total_xof": sum(i.amount for i in invoices),
                                        } if invoices else {"total": 0},
                                    }
                                    return f"Données client « {client.name} » :\n{json.dumps(client_data, ensure_ascii=False, default=str)}"
                except Exception as pf_err:
                    logger.warning("Pre-fetch CRM échoué: %s", pf_err)
                return ""

            (sources, rag_context), prefetch_ctx = await asyncio.gather(
                _do_rag(), _do_prefetch()
            )

            # Injecter contextes dans le message utilisateur
            injected = user_content
            if rag_context:
                injected += f"\n\n## Documents GED disponibles\n{rag_context}"
            if prefetch_ctx:
                injected += f"\n\n## Données CRM (Odoo) déjà chargées — utilise-les directement sans appeler d'outil :\n{prefetch_ctx}"
            if injected != user_content:
                messages[-1] = {"role": "user", "content": injected}

            yield f"data: {json.dumps({'type': 'sources', 'sources': [{'doc_id': s.doc_id, 'filename': s.filename, 'doc_type': s.doc_type.value, 'excerpt': s.excerpt, 'relevance_score': s.relevance_score} for s in _dedup_sources_for_display(sources)]})}\n\n"

            # ── 4. Boucle agentique avec streaming réel ────────────────────
            full_answer = ""
            max_iterations = 6  # Agent réel : jusqu'à 5 appels d'outils + réponse finale
            called_tools: dict[str, int] = {}  # nom_outil → nb_appels (anti-boucle)

            for iteration in range(max_iterations):
                collected_text = ""
                pending_tool_calls = []
                pending_assistant_message = None
                # On bufférise à CHAQUE itération : le texte qui précède un appel d'outil
                # est du "thinking"/préambule (« Laisse-moi chercher… ») et doit être jeté,
                # pas seulement à l'itération 0. Seul le texte de l'itération FINALE (sans
                # outil) est restitué à l'utilisateur via le flush plus bas.
                buffer_only = True
                token_buffer: list[str] = []

                async for event in llm.agentic_stream(
                    system=_get_system_prompt(),
                    messages=messages,
                    tools=_CRM_TOOLS,
                    max_tokens=1500,
                ):
                    if event["type"] == "token":
                        collected_text += event["content"]
                        if buffer_only:
                            token_buffer.append(event["content"])
                        else:
                            yield f"data: {json.dumps({'type': 'token', 'content': event['content']})}\n\n"
                    elif event["type"] == "tool_calls":
                        pending_tool_calls = event["calls"]
                        pending_assistant_message = event["assistant_message"]
                        collected_text = event.get("text", collected_text)
                        # L'IA a appelé un outil → le texte bufférisé était du "thinking" → on l'efface
                        token_buffer = []
                    elif event["type"] == "end":
                        collected_text = event["text"]

                # Fin — pas d'outils : réponse finale
                if not pending_tool_calls:
                    full_answer = collected_text
                    if buffer_only:
                        # Itération finale (aucun outil appelé) : on restitue le buffer,
                        # c.-à-d. la VRAIE réponse — les préambules des tours précédents
                        # ont déjà été jetés au moment de leur tool_call.
                        for chunk in token_buffer:
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                    break

                # Anti-boucle : limites par outil
                # executer_analyse_sql : max 4 appels (chaque SQL peut être différent)
                # autres outils : max 2 appels
                blocked = True
                for call in pending_tool_calls:
                    n = call["name"]
                    limit = 4 if n in ("executer_analyse_sql", "interroger_documents") else 2
                    if called_tools.get(n, 0) < limit:
                        blocked = False
                        break
                if blocked and iteration > 0:
                    logger.info("Boucle détectée (iter %d), arrêt anticipé", iteration)
                    full_answer = collected_text or "Je n'ai pas trouvé cette information dans les données disponibles."
                    break
                for call in pending_tool_calls:
                    called_tools[call["name"]] = called_tools.get(call["name"], 0) + 1

                # ── 4. Exécuter les outils avec progress streaming ──────────
                tool_results = []
                for call in pending_tool_calls:
                    tool_label = _TOOL_LABELS.get(call["name"], f"Exécution de {call['name']}…")
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': call['name'], 'label': tool_label})}\n\n"

                    content, is_error = await _execute_tool(
                        call["name"], call["input"], crm_repo, rag_engine,
                        doc_registry=container.doc_registry,
                        ro_sql=container.ro_sql,
                    )
                    if is_error:
                        logger.warning("Tool %s échoué (iter %d): %s", call["name"], iteration, content[:100])

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "is_error": is_error,
                        "content": content,
                    })

                messages.append(pending_assistant_message)
                messages.append({"role": "user", "content": tool_results})

            else:
                full_answer = "Réponse incomplète (limite de tours atteinte)."
                yield f"data: {json.dumps({'type': 'token', 'content': full_answer})}\n\n"

            # ── 5. Sauvegarder la mémoire ───────────────────────────────────
            if session_id_val and full_answer:
                await _save_turns(session_id_val, [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": full_answer},
                ], user_id=current_user.id, profile=profile_val)

            final_intent = intent_hint or "rag"
            yield f"data: {json.dumps({'type': 'done', 'intent': final_intent})}\n\n"

        except Exception as exc:
            logger.error("Erreur event_stream: %s\n%s", exc, traceback.format_exc())
            exc_str = str(exc).lower()
            if "overloaded" in exc_str:
                msg = "L'IA est temporairement surchargée. Veuillez réessayer dans quelques secondes."
            elif "connection error" in exc_str or "connecterror" in exc_str or "connection refused" in exc_str:
                msg = ("Tous les modèles IA sont indisponibles (surcharge + quota OpenAI épuisé + "
                       "Ollama non démarré). Installez Ollama sur ollama.ai puis : ollama pull llama3.1")
            elif "insufficient_quota" in exc_str:
                msg = "Quota OpenAI épuisé. Vérifiez le crédit sur platform.openai.com."
            else:
                msg = f"Erreur IA : {exc}"
            yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'intent': 'error'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions")
async def list_sessions(current_user: CurrentUser, profile: str = "", limit: int = 30):
    """Liste les conversations récentes de l'utilisateur (groupées par session).

    Cloisonné par profil cockpit : sans `profile` valide, la liste est vide
    plutôt que globale — deux profils ne doivent jamais se voir l'un l'autre.
    """
    profile_val = _normalize_profile(profile)
    if not profile_val:
        return {"sessions": []}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                ConversationModel.session_id,
                func.min(ConversationModel.created_at).label("started_at"),
                func.max(ConversationModel.created_at).label("last_at"),
                func.count(ConversationModel.id).label("turn_count"),
            )
            .where(
                ConversationModel.user_id == current_user.id,
                ConversationModel.profile == profile_val,
            )
            .group_by(ConversationModel.session_id)
            .order_by(func.max(ConversationModel.created_at).desc())
            .limit(limit)
        )
        sessions_rows = result.all()

    if not sessions_rows:
        return {"sessions": []}

    # Pour chaque session, récupérer le premier message utilisateur comme titre
    session_ids = [r.session_id for r in sessions_rows]
    async with AsyncSessionLocal() as session:
        first_msgs_result = await session.execute(
            select(ConversationModel.session_id, ConversationModel.content)
            .where(
                ConversationModel.user_id == current_user.id,
                ConversationModel.profile == profile_val,
                ConversationModel.session_id.in_(session_ids),
                ConversationModel.role == "user",
            )
            .order_by(ConversationModel.session_id, ConversationModel.created_at.asc())
        )
        first_msgs_rows = first_msgs_result.all()

    # Garder uniquement le premier message par session
    first_msg_by_session: dict[str, str] = {}
    for row in first_msgs_rows:
        if row.session_id not in first_msg_by_session:
            first_msg_by_session[row.session_id] = row.content[:120]

    sessions_list = [
        {
            "session_id": r.session_id,
            "title": first_msg_by_session.get(r.session_id, "Conversation")[:80],
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "last_at": r.last_at.isoformat() if r.last_at else None,
            "turn_count": r.turn_count,
        }
        for r in sessions_rows
    ]
    return {"sessions": sessions_list}


@router.get("/sessions/{session_id}")
async def get_session_history(session_id: str, current_user: CurrentUser, profile: str = ""):
    """Retourne l'historique complet d'une session pour la reprendre."""
    profile_val = _normalize_profile(profile)
    if not profile_val:
        return {"session_id": session_id, "messages": []}
    db_history = await _load_history(
        session_id, user_id=current_user.id, profile=profile_val, limit=100
    )
    return {"session_id": session_id, "messages": db_history}


@router.delete("/session/{session_id}")
async def clear_session(session_id: str, current_user: CurrentUser, profile: str = ""):
    """Supprime une conversation de l'historique de l'utilisateur."""
    conditions = [
        ConversationModel.session_id == session_id,
        ConversationModel.user_id == current_user.id,
    ]
    profile_val = _normalize_profile(profile)
    if profile_val:
        conditions.append(ConversationModel.profile == profile_val)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ConversationModel).where(*conditions))
        await session.commit()
    return {"status": "cleared", "session_id": session_id}


@router.post("/query/sync", response_model=ChatResponse)
async def chat_query_sync(body: ChatRequest, request: Request):
    """Version non-streamée pour les tests."""
    use_case = CapitalKnowledgeUseCase(dispatcher=request.app.state.container.query_dispatcher)
    result = await use_case.query(
        text=body.text,
        history=[t.model_dump() for t in body.history],
        session_id=body.session_id,
    )
    return ChatResponse(
        answer=result.answer,
        intent=result.intent.value,
        sources=[
            SourceSchema(
                doc_id=s.doc_id, filename=s.filename, doc_type=s.doc_type.value,
                excerpt=s.excerpt, relevance_score=s.relevance_score,
            )
            for s in _dedup_sources_for_display(result.sources)
        ],
    )
