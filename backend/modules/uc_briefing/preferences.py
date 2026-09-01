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

  - intercontrat, taux d'occupation, complétude des timesheets (trame DO) :
    `account.analytic.line` n'est pas synchronisé, et aucune table de saisie des
    temps n'existe. Le modèle d'affaires ne s'y prête pas non plus — le CA se
    fait en intégration (Cisco 10 393 M, Fortinet 5 288 M, Dell 4 732 M), pas en
    régie : 358 lignes de commande sur 14 767 évoquent un jour/homme.
  - devis à relancer, taux de transformation devis → commande (trame DC) :
    `sale_orders.state` vaut `sale` sur les 3 108 lignes du miroir. Aucun devis
    (`draft` / `sent`) n'est synchronisé et `validity_date` n'existe pas ici.
    Il n'y a rien à relancer tant que la synchronisation ne les ramène pas.
  - position de trésorerie (trame DAF) : `account.payment` et
    `account.bank.statement.line` ne sont pas synchronisés. Le solde relevé à
    l'audit n'est pas dans l'application.
  - taux de couverture du pipe par rapport à l'objectif : `commercial_objectives`
    est vide. Le numérateur existe, le dénominateur non — et le dériver ferait
    passer une hypothèse pour une cible votée.

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

    `question` porte la QUESTION MÉTIER à laquelle l'élément répond, mot pour mot
    celle de la trame de briefing quotidien. C'est le champ qui a réorienté tout
    le catalogue : construit à l'envers — en inventoriant ce que le CRM savait
    agréger — il produisait un briefing qui répondait à « qu'est-ce qu'on sait
    calculer ? » et non à « qu'est-ce que ce directeur se demande le matin ? ».
    Un élément sans `question` est un COMPLÉMENT : il reste disponible, il
    n'arrive jamais dans le briefing sans un geste explicite.

    `bloc` donne la forme attendue d'un briefing utile, en trois temps :
    le chiffre et son mouvement, les exceptions, ce qu'on fait aujourd'hui.
    C'est lui qui ordonne les puces — l'ordre du code n'a aucune raison de
    correspondre à l'ordre de lecture.
    """
    id: str
    libelle: str
    description: str
    defaut: bool
    question: str = ""
    bloc: str = "chiffre"


# Ordre de lecture d'un briefing. Les puces sortent triées par bloc, puis par
# position dans le catalogue du rôle — jamais dans l'ordre où le code les a
# produites, qui suit les dépendances de calcul et non l'urgence.
#
# `couverture` passe après tout : c'est la ligne qui dit quelles questions sont
# restées sans réponse, utile mais jamais prioritaire sur un fait.
# `complement` ferme la marche : un élément hors trame ne doit jamais précéder
# une réponse à une question posée.
ORDRE_BLOCS = ("chiffre", "alerte", "action", "couverture", "complement")


# ── Catalogue par rôle ────────────────────────────────────────────────────────
# UN ÉLÉMENT = UNE QUESTION de la trame, dans l'ordre de la trame. Les agrégats
# qui ne répondent à aucune question n'ont pas disparu : ils sont marqués
# `bloc="complement"`, sans `question`, et décochés.
#
# Les défauts sont désormais EXACTEMENT les éléments porteurs d'une question.
# Auparavant les six éléments cochés du directeur commercial ne répondaient à
# aucune : le briefing par défaut était intégralement hors trame, et personne ne
# pouvait s'en apercevoir depuis l'écran.
#
# CE QUI N'EST PAS AU CATALOGUE, et pourquoi — vérifié sur la base réelle :
#   - renouvellements de contrats : la table `contracts` est VIDE (0 ligne). La
#     case serait structurellement muette, ce qui est pire qu'une case absente :
#     elle fait croire à un réglage qui n'a aucun effet. C'est `deadline` sur les
#     opportunités qui porte réellement les échéances.
#   - répartition sectorielle : `clients.sector` est rempli pour 1 client sur
#     1 508. La puce dirait « 100 % Non renseigné ».
#   - montée en valeur (`get_cross_sell_opportunities`) : la méthode exige un
#     `product_anchor` obligatoire — elle répond « qui a acheté X et pas Y », pas
#     « où sont les occasions ». En coder un en dur ferait passer un choix
#     arbitraire pour une priorité commerciale.
#
# Les questions de la trame SANS réponse possible ne deviennent pas des cases
# muettes non plus : elles sont déclarées dans `SANS_REPONSE` et restituées en
# une seule ligne de couverture (cf. l'élément `questions_sans_reponse`).

CATALOGUE: dict[str, list[Element]] = {
    # ═══ Direction générale — ratios croisés et points de rupture ═══════════
    # Format voulu par la trame : cinq chiffres, trois alertes, trois
    # arbitrages. Pas plus.
    "dg": [
        Element("ca_ytd", "CA à date comparable",
                "Le CA commandé au jour J face au même jour de l'an dernier, en montant et en nombre de commandes.",
                True, "Où en est l'exercice à date comparable ?", "chiffre"),
        Element("visibilite_carnet", "Visibilité du carnet",
                "Combien de mois de facturation le backlog couvre, face au plancher retenu.",
                True, "Combien de mois de visibilité j'ai ?", "chiffre"),
        Element("book_to_bill", "Book-to-bill",
                "Ce qui est commandé rapporté à ce qui est facturé : le carnet se remplit-il plus vite qu'il ne se vide.",
                True, "Est-ce que je remplis plus vite que je ne consomme ?", "chiffre"),
        Element("marge_exercice", "Marge de l'exercice",
                "La marge provisoire et définitive de l'exercice, en montant et en pourcentage du CA.",
                True, "Est-ce que je gagne de l'argent ?", "chiffre"),
        Element("position_tresorerie", "Position nette de trésorerie",
                "Ce qui est dû aux fournisseurs face à ce qui reste à encaisser, et le découvert structurel entre les deux.",
                True, "Est-ce que je serai payé ?", "chiffre"),
        Element("croisement_impaye_rupture", "Impayé croisé avec silence",
                "Les comptes qui cumulent une dette échue et un arrêt de commande — le cas à trancher.",
                True, "Quels sont mes 3 risques du jour ?", "alerte"),
        Element("rupture_rythme", "Comptes en rupture de rythme",
                "Les comptes majeurs qui ont cessé de commander, nommés et datés, avec le CA historique en jeu.",
                True, "Quels sont mes 3 risques du jour ?", "alerte"),
        Element("concentration", "Concentration du portefeuille",
                "La part du top 5 dans le CA de l'exercice, rapportée au seuil de vigilance.",
                True, "Quels sont mes 3 risques du jour ?", "alerte"),
        Element("file_arbitrage", "Arbitrages en attente",
                "Les dossiers qu'aucune direction ne peut trancher seule, avec l'enjeu et le coût d'une semaine de report.",
                True, "Quelles décisions m'attendent ?", "action"),
        Element("questions_sans_reponse", "Questions restées sans réponse",
                "Les questions de la trame que les données ne permettent pas de traiter aujourd'hui, et ce qui les bloque.",
                True, "", "couverture"),
        # ── Compléments : hors trame, décochés ───────────────────────────────
        Element("taux_materialisation", "Matérialisation du CA",
                "La part du provisoire devenue définitive face à son seuil, et le backlog non encore facturé.",
                False, "", "complement"),
        Element("retention_clients", "Rétention et churn",
                "Combien de clients de l'an dernier ont recommandé cette année, combien sont perdus, combien sont nouveaux.",
                False, "", "complement"),
        Element("engagement_fournisseurs", "Engagement fournisseurs",
                "Le montant fournisseur restant dû et les fournisseurs qui concentrent l'engagement.",
                False, "", "complement"),
        Element("ca_pluriannuel", "CA pluriannuel",
                "Le CA commandé des cinq derniers exercices, la meilleure année et où se situe l'exercice en cours.",
                False, "", "complement"),
        Element("prevision_atterrissage", "Prévision d'atterrissage",
                "Le réalisé du trimestre en cours et la projection de fin de trimestre, du pessimiste à l'optimiste.",
                False, "", "complement"),
        Element("taux_transformation", "Taux de transformation",
                "La part des affaires gagnées en nombre et en valeur, et le client qui concentre les pertes.",
                False, "", "complement"),
        Element("echeances_affaires", "Affaires à échéance",
                "Les opportunités encore ouvertes dont la clôture tombe dans la fenêtre retenue.",
                False, "", "complement"),
        Element("delai_encaissement", "Délai d'encaissement",
                "Le délai réel entre facturation et paiement, le retard moyen des impayés et le taux de recouvrement.",
                False, "", "complement"),
        Element("performance_commerciaux", "Performance par commercial",
                "La répartition du réalisé de l'exercice entre commerciaux, et qui le porte.",
                False, "", "complement"),
        Element("mix_sectoriel", "Mix sectoriel",
                "La répartition du CA de l'exercice par secteur client, et le secteur dominant.",
                False, "", "complement"),
        Element("rythme_mensuel", "Rythme mensuel",
                "Le CA mois par mois de l'exercice, et le dernier mois complet face à la moyenne de l'année.",
                False, "", "complement"),
        Element("affaires_imminentes", "Affaires imminentes",
                "Les opportunités les plus chaudes du pipeline, en score pondéré, et la première d'entre elles.",
                False, "", "complement"),
        Element("factures_echues", "Factures échues",
                "Le stock de factures échues non réglées, côté clients et côté fournisseurs.",
                False, "", "complement"),
    ],

    # ═══ Direction commerciale ══════════════════════════════════════════════
    "dir_commercial": [
        Element("ca_commande_periode", "CA commandé et son mouvement",
                "Ce qui a été commandé depuis le 1er du mois et depuis le 1er janvier, avec la variation depuis hier et sur le mois.",
                True, "Combien j'ai commandé hier / depuis le 1er du mois ?", "chiffre"),
        Element("carnet_commandes", "Carnet de commandes",
                "Ce qui est vendu et pas encore facturé, et son mouvement.",
                True, "Où en est mon carnet de commandes ?", "chiffre"),
        Element("pipeline_ouvert", "Pipeline ouvert et pondéré",
                "Le montant brut et pondéré du pipeline, la part encore dans les temps, et le nombre d'affaires qui le portent.",
                True, "Mon pipeline couvre-t-il encore mon objectif ?", "chiffre"),
        # « Ce qui a bougé » précède le taux de transformation : c'est l'ordre de
        # la trame (question 4 contre question 9), et le résumé de tête ne retient
        # que trois chiffres — le mouvement du jour y a sa place, un taux
        # d'exercice beaucoup moins.
        Element("mouvements_recents", "Ce qui a bougé",
                "Les commandes entrées, factures émises, règlements reçus et changements d'étape des sept derniers jours.",
                True, "Qu'est-ce qui a bougé dans le pipe ?", "chiffre"),
        Element("taux_victoire", "Taux de transformation",
                "La part des affaires gagnées, en nombre et en valeur.",
                True, "Quel est mon taux de transformation ?", "chiffre"),
        Element("hygiene_pipe", "Ce qui dort, ce qui est périmé",
                "Les affaires encore dans les temps qui ne bougent plus, et le stock d'opportunités dont l'échéance est déjà passée.",
                True, "Qu'est-ce qui dort ?", "alerte"),
        Element("echeances_opportunites", "Échéances à venir",
                "Les affaires encore ouvertes dont la clôture tombe dans la fenêtre retenue — ce qu'il faut relancer avant qu'il ne soit trop tard.",
                True, "Quelles affaires vont expirer ?", "alerte"),
        Element("concentration_clients", "Dépendance aux plus gros comptes",
                "La part du commandé portée par le top 3 et le top 5, face au seuil de vigilance.",
                True, "Suis-je trop dépendant d'un client ?", "alerte"),
        Element("questions_sans_reponse", "Questions restées sans réponse",
                "Les questions de la trame que les données ne permettent pas de traiter aujourd'hui, et ce qui les bloque.",
                True, "", "couverture"),
        # ── Compléments ──────────────────────────────────────────────────────
        Element("forecast_scenarios", "Fourchette de forecast",
                "Les trois scénarios à six mois — pessimiste, réaliste, optimiste.",
                False, "", "complement"),
        Element("pertes_par_client", "Où se concentrent les pertes",
                "Le client qui concentre le plus d'opportunités perdues, en montant et en nombre.",
                False, "", "complement"),
        Element("top_lead", "Lead le plus chaud",
                "L'opportunité au meilleur score pondéré du pipeline.",
                False, "", "complement"),
        Element("couverture_objectifs", "Réalisé par commercial",
                "La répartition du réalisé de l'exercice entre commerciaux.",
                False, "", "complement"),
        Element("mix_offre", "Mix d'offre",
                "La répartition du CA par famille d'offre sur l'exercice.",
                False, "", "complement"),
    ],

    # ═══ Direction administrative et financière ═════════════════════════════
    "dir_financier": [
        Element("balance_agee", "Balance âgée client",
                "Les créances par tranche d'ancienneté — à échoir, 0-30, 30-60, 60-90, au-delà — et la part en contentieux.",
                True, "Qu'est-ce qui reste dû, et depuis quand ?", "chiffre"),
        Element("dso_glissant", "DSO glissant",
                "Le délai réel d'encaissement sur douze mois glissants, face à la période précédente.",
                True, "Mon DSO se dégrade-t-il ?", "chiffre"),
        Element("ca_facture_periode", "CA facturé et encaissé",
                "Ce qui a été facturé et encaissé sur le mois et sur l'exercice, face au commandé, avec leur mouvement.",
                True, "Où en est le CA facturé du mois ?", "chiffre"),
        Element("attente_facturation", "CA en attente de facturation",
                "Ce qui est vendu et pas encore facturé, et ce que cela représente face au facturé mensuel.",
                True, "Combien de CA dort en attente de facturation ?", "chiffre"),
        Element("marge_definitive", "Marge brute constatée",
                "La marge réellement constatée sur les dossiers arrêtés, rapportée au CA définitif.",
                True, "Ma marge brute tient-elle ?", "chiffre"),
        Element("relances_du_jour", "Relances du jour",
                "Les clients à relancer aujourd'hui, groupés par débiteur, avec leur retard maximal.",
                True, "Qui dois-je relancer aujourd'hui ?", "action"),
        Element("echeancier_fournisseurs", "Échéances fournisseurs",
                "Ce qu'il faudra décaisser aux fournisseurs à 30, 60 et 90 jours, et qui concentre cet engagement.",
                True, "Quelles sont mes échéances fournisseurs ?", "alerte"),
        Element("ecart_marge_promise", "Écart marge prévue / réelle",
                "La distance entre la marge annoncée à l'ouverture des dossiers et celle constatée à l'arrêté.",
                True, "Ma marge brute tient-elle ?", "alerte"),
        Element("questions_sans_reponse", "Questions restées sans réponse",
                "Les questions de la trame que les données ne permettent pas de traiter aujourd'hui, et ce qui les bloque.",
                True, "", "couverture"),
        # ── Compléments ──────────────────────────────────────────────────────
        # `exposition_impayes`, `retard_90j` et `top_debiteur` sont ABSORBÉS par
        # `balance_agee` et `relances_du_jour`, qui portent les mêmes montants
        # avec la ventilation et le nom du débiteur en plus. Les cocher tous
        # produirait trois puces parlant du même encours.
        Element("exposition_impayes", "Exposition aux impayés",
                "Le montant total dû et le nombre de factures concernées, sans ventilation.",
                False, "", "complement"),
        Element("retard_90j", "Retard au-delà de 90 jours",
                "La part la plus ancienne de l'exposition, celle qui ne rentrera pas seule.",
                False, "", "complement"),
        Element("top_debiteur", "Plus gros débiteur",
                "Le client nommé qui porte le plus gros impayé, avec son retard maximal.",
                False, "", "complement"),
        Element("encaissable_vs_du", "À encaisser face à ce qui est dû",
                "Le reste à encaisser des clients face au restant dû aux fournisseurs.",
                False, "", "complement"),
        Element("forecast_trimestre", "Prévision de trimestre",
                "L'atterrissage réaliste du trimestre en cours.",
                False, "", "complement"),
    ],

    # ═══ Direction des opérations ═══════════════════════════════════════════
    # Les questions sont RÉÉCRITES autour du dossier, et ne reprennent pas la
    # trame mot pour mot. Celle-ci décrit une ESN en régie — intercontrat, TJM,
    # taux d'occupation, complétude des timesheets — quand l'activité se fait en
    # intégration (Cisco 10 393 M, Fortinet 5 288 M, Dell 4 732 M) et que 358
    # lignes de commande sur 14 767 seulement évoquent un jour/homme. Importer
    # ces questions telles quelles laisserait cinq cases muettes sur huit.
    "dir_operations": [
        Element("backlog", "Carnet à produire",
                "Ce qui est vendu mais pas encore facturé, son mouvement, et le restant dû aux fournisseurs.",
                True, "Où en est mon carnet à produire ?", "chiffre"),
        Element("volume_marges", "Marge par dossier",
                "Le nombre de dossiers en base, avec les marges provisoire et définitive rapportées au CA.",
                True, "Quelle est ma marge par mission ?", "chiffre"),
        Element("derive_budgetaire", "Dossiers qui dérivent",
                "Les dossiers dont la dépense constatée dévore la dépense prévue, et l'écart entre marge annoncée et marge réelle.",
                True, "Quelles missions dérivent ?", "alerte"),
        Element("sous_traitance_dossiers", "Sous-traitance par dossier",
                "L'engagement fournisseur rapporté au dossier qu'il sert, et les dossiers qui achètent plus qu'ils ne rapportent.",
                True, "Ma sous-traitance est-elle sous contrôle ?", "alerte"),
        Element("fiabilite_fournisseurs", "Fournisseurs qui retardent",
                "Les fournisseurs dont les encours et les retards pèsent sur les dossiers en cours.",
                True, "Quels fournisseurs mettent mes projets en retard ?", "alerte"),
        Element("risque_rupture_fournisseur", "Concentration fournisseur",
                "Les fournisseurs sur lesquels l'engagement se concentre — autant de points de défaillance unique.",
                True, "Où se concentre mon risque fournisseur ?", "alerte"),
        Element("commandes_recentes", "Ce qui vient d'entrer",
                "Les commandes des derniers jours, celles qui viennent d'arriver en production.",
                True, "Qu'est-ce qui vient d'entrer en production ?", "chiffre"),
        Element("questions_sans_reponse", "Questions restées sans réponse",
                "Les questions de la trame que les données ne permettent pas de traiter aujourd'hui, et ce qui les bloque.",
                True, "", "couverture"),
        # ── Compléments ──────────────────────────────────────────────────────
        Element("top_dossier_marge", "Dossier le plus margé",
                "Le dossier au plus fort apport de marge provisoire.",
                False, "", "complement"),
        Element("dossiers_marge_faible", "Dossiers à marge dégradée",
                "Les dossiers dont la marge provisoire est la plus basse — l'inverse du palmarès.",
                False, "", "complement"),
        Element("charge_par_practice", "Charge par famille d'offre",
                "La répartition du CA par famille de prestation sur l'exercice.",
                False, "", "complement"),
    ],

    # ═══ Commercial de terrain ══════════════════════════════════════════════
    # La trame ne définit pas ce profil : ses questions sont celles du directeur
    # commercial, restreintes à ce qui reste vrai sans filtre par personne.
    "commercial": [
        Element("pipeline_perso", "Pipeline ouvert",
                "Le nombre d'opportunités ouvertes et le montant pondéré au scénario réaliste.",
                True, "Où en est mon pipeline ?", "chiffre"),
        Element("taux_victoire_nb", "Taux de transformation",
                "La part des affaires gagnées, en nombre.",
                True, "Quel est mon taux de transformation ?", "chiffre"),
        Element("mouvements_recents", "Ce qui a bougé",
                "Les commandes, factures, règlements et changements d'étape des sept derniers jours, sur tout le portefeuille S2I.",
                True, "Qu'est-ce qui a bougé ?", "chiffre"),
        Element("hygiene_pipe", "Ce qui dort, ce qui est périmé",
                "Les affaires encore dans les temps qui ne bougent plus, et le stock d'opportunités à échéance dépassée.",
                True, "Qu'est-ce qui dort ?", "alerte"),
        Element("echeances_opportunites", "Échéances à venir",
                "Les affaires encore ouvertes dont la clôture tombe dans la fenêtre retenue.",
                True, "Quelles affaires vont expirer ?", "alerte"),
        Element("comptes_silencieux", "Comptes qui ont décroché",
                "Les comptes sans commande depuis trop longtemps, nommés et datés.",
                True, "Quels comptes ont décroché ?", "alerte"),
        Element("impayes_portefeuille", "Impayés qui bloquent",
                "Les factures échues qui bloquent les prochaines commandes.",
                True, "Quels impayés bloquent mes prochaines commandes ?", "alerte"),
        Element("questions_sans_reponse", "Questions restées sans réponse",
                "Les questions de la trame que les données ne permettent pas de traiter aujourd'hui, et ce qui les bloque.",
                True, "", "couverture"),
        # ── Compléments ──────────────────────────────────────────────────────
        Element("top_lead", "Lead le plus chaud",
                "L'opportunité au meilleur score pondéré, avec son étape.",
                False, "", "complement"),
        Element("deals_perdus", "Affaires perdues récemment",
                "Les opportunités perdues, et les clients sur lesquels elles se concentrent.",
                False, "", "complement"),
    ],
}

# ATTENTION — périmètre du rôle `commercial` : aucune des sources utilisées par
# ses éléments n'est filtrée par commercial. `get_account_rhythm_breaks` et
# `get_unpaid_exposure` renvoient l'ENTREPRISE ENTIÈRE. Les libellés ci-dessus
# disent donc « Comptes qui ont décroché » et jamais « mes comptes », et les
# puces correspondantes nomment leur périmètre. Un filtre par commercial suppose
# de résoudre les 32 orthographes distinctes de `salesperson_name` via
# SalespersonModel et ses alias — chantier distinct, pas un ajustement.


# ── Questions de la trame restées sans réponse ───────────────────────────────
# Elles ne deviennent PAS des cases muettes — la doctrine du catalogue l'interdit
# — mais elles ne disparaissent pas non plus : le briefing les restitue en une
# ligne unique, avec leur cause. Une seule ligne, et non une puce d'aveu par
# question : la direction des opérations en compterait cinq sur huit.
#
# Cette ligne est aussi un levier : elle met sous les yeux de chaque direction ce
# que la qualité du référentiel Odoo lui coûte, chaque matin.
SANS_REPONSE: dict[str, list[tuple[str, str]]] = {
    "dg": [
        ("La machine tourne-t-elle à plein ?",
         "aucune saisie des temps n'est synchronisée"),
        ("Quelle est ma marge par BU ?",
         "le miroir ne porte aucune notion d'unité d'affaires"),
        ("Quel est mon cash disponible ?",
         "les paiements et relevés bancaires ne sont pas synchronisés"),
    ],
    "dir_commercial": [
        ("Quels devis vont expirer ?",
         "aucun devis n'est synchronisé, toutes les commandes du miroir sont déjà confirmées"),
        ("Est-ce que je vends au bon prix (TJM) ?",
         "sans objet — l'activité se fait en intégration, pas en régie"),
        ("Mon pipe couvre-t-il mon objectif ?",
         "le pipe est mesuré, mais aucun objectif n'est saisi en base"),
    ],
    "dir_financier": [
        ("Quelle est ma position de trésorerie ?",
         "les paiements et relevés bancaires ne sont pas synchronisés"),
        ("Ai-je des engagements réceptionnés non facturés ?",
         "les lignes de commande d'achat ne sont pas synchronisées"),
        ("Où en est le facturé face à l'objectif ?",
         "le facturé est mesuré, mais aucun objectif n'est saisi en base"),
    ],
    "dir_operations": [
        ("Qui est en intercontrat, quel est mon taux d'occupation ?",
         "aucune saisie des temps n'est synchronisée, et l'activité ne se fait pas en régie"),
        ("Quelles missions se terminent bientôt ?",
         "la date de fin n'est renseignée que sur 9 dossiers sur 2 392"),
        ("Le consommé dépasse-t-il le vendu, ligne à ligne ?",
         "les quantités livrées et facturées valent zéro sur les 19 510 lignes du miroir"),
    ],
    "commercial": [
        ("Quels devis dois-je relancer ?",
         "aucun devis n'est synchronisé"),
        ("Où en est mon portefeuille à moi ?",
         "les sources ne sont pas filtrables par commercial — 32 orthographes distinctes de vendeur"),
    ],
}


DEFAUTS: dict[str, list[str]] = {
    role: [e.id for e in elements if e.defaut] for role, elements in CATALOGUE.items()
}


def rang(role: str, element_id: str) -> tuple[int, int]:
    """Position de lecture d'un élément : (rang du bloc, rang dans le rôle).

    Un identifiant inconnu passe en dernier plutôt que de lever : un élément
    retiré du catalogue mais encore cité par une composition enregistrée ne doit
    pas coûter le briefing.
    """
    for index, element in enumerate(CATALOGUE.get(role, [])):
        if element.id == element_id:
            bloc = element.bloc if element.bloc in ORDRE_BLOCS else "complement"
            return (ORDRE_BLOCS.index(bloc), index)
    # Identifiant inconnu : rangé avec les compléments plutôt qu'au-delà du
    # dernier bloc — un rang hors bornes ferait déborder toute indexation de
    # `ORDRE_BLOCS` chez l'appelant (cf. Puces.par_bloc).
    return (ORDRE_BLOCS.index("complement"), 9999)


def questions_de(role: str) -> list[str]:
    """Questions couvertes par le rôle, dans l'ordre de lecture, sans doublon.

    Plusieurs éléments peuvent répondre à la même question — les trois alertes
    du directeur général répondent toutes à « quels sont mes 3 risques du
    jour ? ». La liste les fusionne.
    """
    vues: list[str] = []
    for element in CATALOGUE.get(role, []):
        if element.question and element.question not in vues:
            vues.append(element.question)
    return vues


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
