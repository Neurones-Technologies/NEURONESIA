"""Composition du débrief quotidien : catalogue des éléments cochables par rôle,
et persistance des choix.

Le catalogue et la persistance vivent dans le même module parce qu'ils sont
indissociables : valider un identifiant relu en base exige de connaître le
catalogue du rôle, et l'écran de réglages a besoin des deux dans la même réponse.

DOCTRINE — les préférences NE DOIVENT PAS vivre dans data/briefing_store/latest.json.
Ce fichier est un cache jetable : `scripts/purge_partenaires_exclus.py` le supprime
(« briefing figé supprimé, régénéré au prochain cron ») et `service.generate` le
réécrit en entier. Une préférence qui y serait rangée disparaîtrait à la première
purge, sans trace ni message. D'où la table `briefing_preferences`.

CE QUI N'EST PAS AU CATALOGUE, et pourquoi — vérifié sur la base réelle :
  - renouvellements de contrats (`get_expiring_contracts`) : la table `contracts`
    est VIDE (0 ligne). La case serait structurellement muette, ce qui est pire
    qu'une case absente : elle fait croire à un réglage qui n'a aucun effet.
    C'est `deadline` sur les opportunités qui porte réellement les échéances.
  - répartition sectorielle (`get_revenue_by_sector`) : `clients.sector` est
    rempli pour 1 client sur 1380. La puce dirait « 100 % Non renseigné ».
  - top fournisseurs (`get_top_suppliers`) : redondant avec
    `get_supplier_intelligence`, qui porte les mêmes montants ET les indicateurs
    décisionnels (retards, concentration, échéancier).
  - montée en valeur (`get_cross_sell_opportunities`) : la méthode exige un
    `product_anchor` obligatoire — elle répond « qui a acheté X et pas Y », pas
    « où sont les occasions ». Un briefing quotidien n'a aucun ancrage produit à
    lui fournir, et en coder un en dur ferait passer un choix arbitraire pour une
    priorité commerciale. Demande une agrégation dédiée, pas une case à cocher.

Règle générale : aucun élément n'entre ici sans que sa source ait été vérifiée
non vide sur des données réelles.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import BriefingPreferenceModel

logger = logging.getLogger(__name__)

# Longueur maximale de la consigne libre. Au-delà, une consigne noierait les
# règles du prompt système au lieu de les nuancer (cf. narratif._CONSIGNE_BLOC).
CONSIGNE_MAX = 400

# Version du document `value_json`. Un document de version inconnue est ignoré au
# profit des défauts, plutôt que lu de travers.
VERSION = 1


@dataclass(frozen=True)
class Element:
    """Un élément cochable du débrief.

    `description` dit ce que la PUCE racontera, pas ce que la donnée est : c'est
    ce que lit la personne qui coche, et elle décide d'un contenu de briefing,
    pas d'un branchement technique.
    """
    id: str
    libelle: str
    description: str
    defaut: bool


# ── Catalogue par rôle ────────────────────────────────────────────────────────
# Les éléments marqués `defaut=True` reproduisent le briefing tel qu'il existait
# avant cette fonctionnalité, à une exception près : les éléments qui RÉPARENT
# une promesse déjà faite par narratif.ROLE_FOCUS arrivent cochés eux aussi. Le
# prompt annonce déjà ces sujets au LLM (« les renouvellements et échéances à
# venir », « la couverture par rapport aux objectifs », « la visibilité de charge
# par practice », « la marge réelle par rapport à la marge annoncée ») sans
# qu'aucun fait ne les porte : les livrer décochés reviendrait à livrer le
# correctif éteint.
#
# Tout autre élément nouveau arrive DÉCOCHÉ — personne ne doit voir son débrief
# s'allonger tout seul après un déploiement.

CATALOGUE: dict[str, list[Element]] = {
    "dg": [
        Element("ca_ytd", "CA à date comparable",
                "Le CA commandé au jour J face au même jour de l'an dernier, en montant et en nombre de commandes.",
                True),
        Element("rupture_rythme", "Comptes en rupture de rythme",
                "Les comptes majeurs qui ont cessé de commander, nommés et datés, avec le CA historique en jeu.",
                True),
        Element("croisement_impaye_rupture", "Impayé croisé avec silence",
                "Les comptes qui cumulent une dette échue et un arrêt de commande — le cas à trancher.",
                True),
        Element("file_arbitrage", "File d'arbitrage",
                "Les dossiers qu'aucune direction ne peut trancher seule, avec l'enjeu et le coût d'une semaine de report.",
                True),
        Element("position_tresorerie", "Position nette de trésorerie",
                "Ce qui est dû aux fournisseurs face à ce qui reste à encaisser, et le découvert structurel entre les deux.",
                True),
        Element("concentration", "Concentration du portefeuille",
                "La part du top 5 dans le CA de l'exercice, rapportée au seuil de vigilance de 50 %.",
                True),
        Element("taux_materialisation", "Matérialisation du CA",
                "La part du provisoire devenue définitive face au seuil de 80 %, et le backlog non encore facturé.",
                True),
        Element("retention_clients", "Rétention et churn",
                "Combien de clients de l'an dernier ont recommandé cette année, combien sont perdus, combien sont nouveaux.",
                False),
        Element("engagement_fournisseurs", "Engagement fournisseurs",
                "Le montant fournisseur restant dû et les fournisseurs qui concentrent l'engagement.",
                False),
        # ── Vue 360 (élargissement du pilotage DG) — tous décochés par défaut ──
        Element("ca_pluriannuel", "CA pluriannuel",
                "Le CA commandé des cinq derniers exercices, la meilleure année et où se situe l'exercice en cours.",
                False),
        Element("marge_exercice", "Marge de l'exercice",
                "La marge provisoire et définitive de l'exercice, en montant et en pourcentage moyen.",
                False),
        Element("prevision_atterrissage", "Prévision d'atterrissage",
                "Le réalisé du trimestre en cours et la projection de fin de trimestre, du pessimiste à l'optimiste.",
                False),
        Element("taux_transformation", "Taux de transformation",
                "La part des affaires gagnées en nombre et en valeur, et le client qui concentre les pertes.",
                False),
        Element("echeances_affaires", "Affaires à échéance",
                "Les opportunités encore ouvertes dont la clôture tombe dans les 60 jours, et la plus proche.",
                False),
        Element("delai_encaissement", "Délai d'encaissement",
                "Le délai réel entre facturation et paiement, le retard moyen des impayés et le taux de recouvrement.",
                False),
        Element("performance_commerciaux", "Performance par commercial",
                "La répartition du réalisé de l'exercice entre commerciaux, et qui le porte.",
                False),
        Element("mix_sectoriel", "Mix sectoriel",
                "La répartition du CA de l'exercice par secteur client, et le secteur dominant.",
                False),
        Element("rythme_mensuel", "Rythme mensuel",
                "Le CA mois par mois de l'exercice, et le dernier mois complet face à la moyenne de l'année.",
                False),
        Element("affaires_imminentes", "Affaires imminentes",
                "Les opportunités les plus chaudes du pipeline, en score pondéré, et la première d'entre elles.",
                False),
        Element("factures_echues", "Factures échues",
                "Le stock de factures échues non réglées, côté clients et côté fournisseurs — nombre, montant et part au-delà de 90 jours.",
                False),
    ],
    "dir_commercial": [
        Element("pipeline_ouvert", "Pipeline ouvert",
                "Le montant brut et pondéré du pipeline, et le nombre d'opportunités qui le portent.",
                True),
        Element("forecast_scenarios", "Fourchette de forecast",
                "Les trois scénarios à six mois — pessimiste, réaliste, optimiste.",
                True),
        Element("taux_victoire", "Taux de victoire",
                "La part des affaires gagnées, en nombre et en valeur.",
                True),
        Element("pertes_par_client", "Où se concentrent les pertes",
                "Le client qui concentre le plus d'opportunités perdues, en montant et en nombre.",
                True),
        Element("top_lead", "Lead le plus chaud",
                "L'opportunité au meilleur score pondéré du pipeline.",
                True),
        # Répare ROLE_FOCUS["dir_commercial"] : « les opportunités qui glissent ».
        Element("echeances_opportunites", "Échéances à 60 jours",
                "Les opportunités encore ouvertes dont la date de clôture tombe dans les deux mois.",
                True),
        Element("couverture_objectifs", "Couverture des objectifs",
                "L'écart entre le vendu et l'objectif de la période, par commercial.",
                False),
        Element("mix_offre", "Mix d'offre",
                "La répartition du CA par famille d'offre sur l'exercice.",
                False),
    ],
    "dir_financier": [
        Element("exposition_impayes", "Exposition aux impayés",
                "Le montant total dû et le nombre de factures concernées.",
                True),
        Element("retard_90j", "Retard au-delà de 90 jours",
                "La part la plus ancienne de l'exposition, celle qui ne rentrera pas seule.",
                True),
        Element("marge_definitive", "Marge définitive moyenne",
                "La marge réellement constatée sur les dossiers arrêtés.",
                True),
        Element("encaissable_vs_du", "À encaisser face à ce qui est dû",
                "Le reste à encaisser des clients face au restant dû aux fournisseurs.",
                True),
        Element("top_debiteur", "Plus gros débiteur",
                "Le client nommé qui porte le plus gros impayé, avec son retard maximal.",
                True),
        Element("forecast_trimestre", "Prévision de trimestre",
                "L'atterrissage réaliste du trimestre en cours.",
                True),
        # Répare ROLE_FOCUS["dir_financier"] : « la marge réelle par rapport à la
        # marge annoncée en début de dossier ».
        Element("ecart_marge_promise", "Écart marge prévue / réelle",
                "La distance entre la marge annoncée à l'ouverture des dossiers et celle constatée à l'arrêté.",
                True),
        Element("echeancier_fournisseurs", "Échéancier fournisseurs",
                "Ce qu'il faudra décaisser aux fournisseurs, et qui concentre cet engagement.",
                False),
    ],
    "dir_operations": [
        Element("volume_marges", "Dossiers et marges moyennes",
                "Le nombre de dossiers en base, avec les marges provisoire et définitive moyennes.",
                True),
        Element("backlog", "Backlog non facturé",
                "Ce qui est vendu mais pas encore facturé, et le restant dû aux fournisseurs.",
                True),
        Element("top_dossier_marge", "Dossier le plus margé",
                "Le dossier au plus fort apport de marge provisoire.",
                True),
        # Répare ROLE_FOCUS["dir_operations"] : « la visibilité de charge par practice ».
        Element("charge_par_practice", "Charge par famille d'offre",
                "La répartition du CA par famille de prestation sur l'exercice.",
                True),
        Element("dossiers_marge_faible", "Dossiers à marge dégradée",
                "Les dossiers dont la marge provisoire est la plus basse — l'inverse du palmarès.",
                False),
        Element("fiabilite_fournisseurs", "Fiabilité des fournisseurs",
                "Les fournisseurs dont les encours et les retards pèsent sur les dossiers en cours.",
                False),
        Element("risque_rupture_fournisseur", "Concentration fournisseur",
                "Les fournisseurs sur lesquels l'engagement se concentre — autant de points de défaillance unique.",
                False),
        Element("commandes_recentes", "Dernières commandes entrées",
                "Les commandes des derniers jours, celles qui viennent d'arriver en production.",
                False),
    ],
    "commercial": [
        Element("pipeline_perso", "Pipeline ouvert",
                "Le nombre d'opportunités ouvertes et le montant pondéré au scénario réaliste.",
                True),
        Element("taux_victoire_nb", "Taux de victoire",
                "La part des affaires gagnées, en nombre.",
                True),
        Element("top_lead", "Lead le plus chaud",
                "L'opportunité au meilleur score pondéré, avec son étape.",
                True),
        # Réparent ROLE_FOCUS["commercial"] : « les ruptures de rythme sur ses
        # propres comptes, les renouvellements et échéances à venir ».
        # NB : ces sources ne sont PAS filtrées par commercial (cf. plus bas).
        Element("echeances_opportunites", "Échéances à 30 jours",
                "Les opportunités encore ouvertes dont la date de clôture tombe dans le mois.",
                True),
        Element("comptes_silencieux", "Comptes qui ont décroché",
                "Les comptes sans commande depuis trop longtemps, nommés et datés.",
                True),
        Element("impayes_portefeuille", "Impayés en cours",
                "Les factures échues qui bloquent les prochaines commandes.",
                False),
        Element("deals_perdus", "Affaires perdues récemment",
                "Les opportunités perdues, et les clients sur lesquels elles se concentrent.",
                False),
    ],
}

# ATTENTION — périmètre du rôle `commercial` : aucune des sources utilisées par
# ses éléments n'est filtrée par commercial. `get_account_rhythm_breaks` et
# `get_unpaid_exposure` renvoient l'ENTREPRISE ENTIÈRE. Les libellés ci-dessus
# disent donc « Comptes qui ont décroché » et jamais « mes comptes », et les
# puces correspondantes nomment leur périmètre. Un filtre par commercial suppose
# de résoudre les 32 orthographes distinctes de `salesperson_name` via
# SalespersonModel et ses alias — chantier distinct, pas un ajustement.

DEFAUTS: dict[str, list[str]] = {
    role: [e.id for e in elements if e.defaut] for role, elements in CATALOGUE.items()
}

_IDS: dict[str, set[str]] = {role: {e.id for e in elements} for role, elements in CATALOGUE.items()}

# ── Cache mémoire ─────────────────────────────────────────────────────────────
# Même compromis que config/permissions.py : invalidation immédiate dans le
# process qui écrit, TTL court comme garde-fou pour les autres workers. La
# lecture est ici très peu fréquente (une par génération de briefing) — le TTL
# est du confort, pas de la performance.
_cache: dict[str, dict] | None = None
_cache_at: float = 0.0
_CACHE_TTL = 30.0


def invalidate_cache() -> None:
    """À appeler après toute écriture dans briefing_preferences."""
    global _cache
    _cache = None


def sanitize_consigne(texte: str) -> str:
    """Nettoie une consigne libre avant stockage.

    Retire les balises `<consigne>` : sans ça, une consigne qui en contient une
    fermante sortirait du bloc délimité du prompt système et se lirait comme une
    instruction de premier rang (cf. narratif._CONSIGNE_BLOC). Écrase aussi les
    lignes vides en série — une consigne de quarante lignes noierait les règles.

    Publique : le routeur s'en sert pour juger si une consigne est exploitable
    avant d'accepter une composition sans aucun élément (mode consigne pilote).
    """
    texte = re.sub(r"</?consigne>", "", texte or "", flags=re.IGNORECASE)
    texte = re.sub(r"\n{2,}", "\n", texte)
    return texte.strip()[:CONSIGNE_MAX]


# Alias de compatibilité : la fonction est née privée et des appelants (tests)
# la connaissent sous ce nom.
_sanitize_consigne = sanitize_consigne


def roles_connus() -> list[str]:
    return list(CATALOGUE.keys())


def catalogue_pour(role: str, actifs: list[str] | None = None) -> list[dict]:
    """Catalogue du rôle, chaque élément portant son état `actif`.

    L'état est calculé ici, côté serveur, et voyage AVEC le catalogue : le
    frontend n'a aucune règle de défaut à réimplémenter, et ne peut pas détenir
    une copie des libellés qui divergerait à la première évolution du catalogue.
    """
    elements = CATALOGUE.get(role, [])
    if actifs is None:
        retenus = set(DEFAUTS.get(role, []))
    else:
        retenus = set(actifs)
    return [
        {"id": e.id, "libelle": e.libelle, "description": e.description, "actif": e.id in retenus}
        for e in elements
    ]


def _document_vide(role: str) -> dict:
    return {
        "elements": list(DEFAUTS.get(role, [])),
        "consigne": "",
        "source": "defaut",
        "updated_by": None,
        "updated_at": None,
    }


def _parse(role: str, row: BriefingPreferenceModel) -> dict:
    """Traduit une ligne en document exploitable, en tolérant tout.

    Un JSON illisible ou d'une version inconnue retombe sur les défauts plutôt
    que de faire échouer la génération du briefing : une préférence corrompue ne
    doit jamais coûter le débrief lui-même.
    """
    try:
        brut = json.loads(row.value_json or "{}")
    except ValueError:
        logger.warning("Préférences de débrief '%s' illisibles — défauts appliqués", role)
        return _document_vide(role)

    if not isinstance(brut, dict) or brut.get("version") != VERSION:
        logger.warning(
            "Préférences de débrief '%s' en version inconnue (%r) — défauts appliqués",
            role, brut.get("version") if isinstance(brut, dict) else None,
        )
        return _document_vide(role)

    connus = _IDS.get(role, set())
    demandes = [e for e in brut.get("elements", []) if isinstance(e, str)]
    elements = [e for e in demandes if e in connus]
    if len(elements) != len(demandes):
        # Élément renommé ou retiré du catalogue : la ligne survit, l'id orphelin
        # est ignoré. Jamais un 500 (même traitement que permissions.get_module_access).
        logger.warning(
            "Préférences de débrief '%s' : %d identifiant(s) inconnu(s) ignoré(s)",
            role, len(demandes) - len(elements),
        )

    return {
        "elements": elements,
        "consigne": sanitize_consigne(brut.get("consigne", "")),
        "source": "reglee",
        "updated_by": row.updated_by or None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def load_all() -> dict[str, dict]:
    """Préférences des cinq rôles, en une seule requête.

    `service.generate` calcule les cinq sections en parallèle : un `load` par
    rôle ferait cinq SELECT dans un `gather` dont les erreurs sont avalées.
    """
    global _cache, _cache_at
    if _cache is not None and time.monotonic() - _cache_at < _CACHE_TTL:
        return _cache

    documents = {role: _document_vide(role) for role in CATALOGUE}
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BriefingPreferenceModel))
        for row in result.scalars():
            if row.role in CATALOGUE:
                documents[row.role] = _parse(row.role, row)

    _cache, _cache_at = documents, time.monotonic()
    return documents


async def load(role: str) -> dict:
    """Préférences d'un rôle. Rôle inconnu ou sans ligne → défauts du catalogue."""
    return (await load_all()).get(role, _document_vide(role))


async def save(role: str, elements: list[str], consigne: str, updated_by: str) -> dict:
    """Remplace la composition d'un rôle. Les ids inconnus sont refusés en amont
    par le routeur — ils sont filtrés ici aussi, par sécurité."""
    if role not in CATALOGUE:
        raise ValueError(f"Rôle inconnu : {role}")

    connus = _IDS[role]
    retenus = [e for e in dict.fromkeys(elements) if e in connus]
    propre = sanitize_consigne(consigne)
    document = {"version": VERSION, "elements": retenus, "consigne": propre}
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as session:
        row = await session.get(BriefingPreferenceModel, role)
        if row is None:
            row = BriefingPreferenceModel(role=role)
            session.add(row)
        row.value_json = json.dumps(document, ensure_ascii=False)
        row.updated_by = updated_by or ""
        row.updated_at = maintenant
        await session.commit()

    invalidate_cache()
    return {
        "elements": retenus,
        "consigne": propre,
        "source": "reglee",
        "updated_by": updated_by or None,
        "updated_at": maintenant.isoformat(),
    }
