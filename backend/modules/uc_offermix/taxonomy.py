"""Taxonomie des familles d'offre — source de vérité UNIQUE du cockpit.

Classe une opportunité dans une famille d'offre (Logiciel / Réseau / Équipement /
Services) à partir de son LIBELLÉ, faute de mieux : le champ catégorie n'existe
pas sur `crm.lead`, et la voie « lignes de commande Odoo » est inexploitable —
mesuré à 40 opportunités sur 6 675 (0,6 %) portant un `order_ids` non vide, les
étapes amont étant à 0 %. Voir docs/ pour les constats de qualité Odoo.

Conséquence assumée : la famille est une ESTIMATION, pas une donnée saisie. Les
libellés en nom de code (« Projet KARANGA », « BABN », « Import ligne 4922 »)
sont structurellement inclassables — d'où `classify_family() -> None` et
l'affichage obligatoire du taux de couverture partout où ces familles sont
montrées. Ne JAMAIS remplacer ce None par une famille « par défaut » : un
non-classé silencieux ferait totaliser les parts à 100 % d'un périmètre inconnu.
(La sentinelle `INDECIDABLE` plus bas n'est pas une telle famille — elle ne sert
qu'à ne pas reclasser indéfiniment un libellé déjà jugé inclassable.)

Deux niveaux de lecture :
- 4 familles hautes (ici) — la lecture du Directeur Commercial ;
- 5 catégories fines du cross-sell (modules/uc_crosssell/aggregation.py) —
  conservées telles quelles, reliées ici par FINE_TO_FAMILY pour qu'aucune
  incohérence n'apparaisse entre les deux tuiles du cockpit.

Convention métier validée avec la Direction Commerciale. Éditable sans
redéploiement du reste : enrichir FAMILY_KEYWORDS relève du paramétrage, et le
backlog d'enrichissement est produit par `uncovered_labels()`.
"""
from __future__ import annotations

import unicodedata

# ── Familles hautes ───────────────────────────────────────────────────────────

FAMILY_LABELS: dict[str, str] = {
    "logiciel": "Logiciel",
    "reseau": "Réseau",
    "equipement": "Équipement",
    "services": "Services",
}

FAMILY_ORDER: list[str] = ["logiciel", "reseau", "equipement", "services"]

# ── Dictionnaire de classement ────────────────────────────────────────────────
# LISTE ORDONNÉE, pas un dict : la priorité est signifiante. Deux règles métier
# portent cet ordre, et les déplacer change les chiffres du cockpit.
#
# 1. SERVICES D'ABORD — la NATURE de l'affaire prime sur son OBJET. « Audit des
#    7 systèmes de vidéosurveillance » est un marché de services : on vend une
#    prestation, pas des caméras. Idem « Formation Cisco » (service, pas réseau)
#    ou « Étude datacenter » (service, pas équipement). Les termes de cette
#    famille sont des actions explicites (audit, formation, étude, déploiement),
#    donc le risque d'attraper à tort une vente de produit est faible.
#
# 2. PUIS DU SPÉCIFIQUE VERS LE GÉNÉRIQUE — « Licence Cisco WAN » doit tomber en
#    `reseau` (le marché est réseau), pas en `logiciel` sur le mot « licence ».
#    D'où Logiciel en dernier : il porte les termes les plus transverses.
#
# Les termes sont comparés SANS ACCENT et en minuscules (cf. _normalize) : écrire
# « reseau » couvre « Réseau », « RESEAU » et « réseaux ». Un terme encadré de
# « | » exige une correspondance de mot entier (cf. _matches).
FAMILY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("services", [
        "formation", "audit", "conseil", "assistance", "|amoa|", "|moa|",
        "|moe|", "|pra|", "|pca|", "continuite", "infogerance", "outsourcing",
        "prestation", "fourniture de services", "accompagnement", "|etude|",
        "|etudes|", "schema directeur", "mise en oeuvre", "mise en service",
        "deploiement", "integration", "migration", "|tma|", "|sla|",
        "expertise", "diagnostic", "cartographie", "gouvernance",
        "certification", "recrutement", "mise a disposition", "|regie|",
        "supervision", "hotline", "helpdesk", "transfert de competence",
        "plan de reprise", "plan de continuite",
    ]),
    ("reseau", [
        "|wan|", "|lan|", "sd-wan", "sdwan", "reseau", "network", "cisco",
        "catalyst", "switch", "router", "routeur", "commutateur", "wifi",
        "wi-fi", "cablage", "fibre", "|mpls|", "|vpn|", "telephonie", "|voip|",
        "|volte|", "|ims|", "|sbc|", "collaboration unifi", "visioconf",
        "|visio|", "backbone", "liaison", "interconnexion", "|cpe|",
        "pop internet", "|nac|", "|ise|", "audio video", "juniper",
        "huawei enterprise", "aruba", "ubiquiti", "starlink", "|vsat|",
        "boucle locale", "|adsl|", "|ftth|",
    ]),
    ("equipement", [
        "datacenter", "data center", "data-center", "serveur", "server",
        "poweredge", "powerstore", "|dell|", "|hpe|", "lenovo", "supermicro",
        "stockage", "storage", "|nas|", "|san|", "|baie|", "|baies|",
        "onduleur", "|ups|", "climatisation", "desktop", "laptop", "ordinateur",
        "poste de travail", "materiel", "hardware", "imprimante", "scanner",
        "videosurveillance", "camera", "tier 3", "tier3", "tier iv",
        "groupe electrogene", "electrogene", "|rack|", "armoire",
        "salle serveur", "salle informatique", "acquisition equipement",
        "fourniture equipement", "tablette", "photocopieur",
        "capacity expansion",
    ]),
    ("logiciel", [
        "licence", "license", "logiciel", "software", "|erp|", "odoo", "|sap|",
        "|crm|", "microsoft", "o365", "m365", "office 365", "azure", "|aws|",
        "cloud", "saas", "virtualisation", "vmware", "vsphere", "esxi",
        "hyper-v", "openshift", "red hat", "linux", "windows", "oracle",
        "base de donnees", "|sql|", "power bi", "powerbi", "analytics", "|ged|",
        "dematerialisation", "workflow", "portail", "application", "applicatif",
        "developpement", "site web", "intranet", "messagerie", "exchange",
        "sharepoint", "|teams|", "abonnement", "subscription",
        # Sécurité — rattachée à Logiciel au niveau haut (cf. FINE_TO_FAMILY).
        # Si le DC veut en faire une 5e famille, c'est ici que ça se décide.
        "antivirus", "firewall", "pare-feu", "fortinet", "fortigate",
        "palo alto", "paloalto", "securite", "security", "|dlp|", "|dns|",
        "|siem|", "|soc|", "|cirt|", "|cert|", "symantec", "varonis",
        "veritas", "big-ip", "|f5|", "|waf|", "|pki|", "|iam|", "|sso|",
        "|mfa|", "endpoint", "|edr|", "|xdr|", "sauvegarde", "backup", "veeam",
        "netbackup", "chiffrement", "kaspersky", "trend micro",
        "work from home", "teletravail",
    ]),
]

# Termes de service GÉNÉRIQUES — passage de dernier recours, appliqué seulement
# si aucune famille produit n'a matché. « Support et maintenance INFRA » doit
# tomber en Services ; « Licence Fortinet + maintenance 3 ans » doit rester en
# Logiciel. Les mettre dans FAMILY_KEYWORDS ci-dessus inverserait ce second cas,
# et contredirait `licences_maintenance -> logiciel` de FINE_TO_FAMILY.
GENERIC_SERVICE_KEYWORDS: list[str] = [
    "support", "maintenance", "contrat cadre", "contrat-cadre",
]

# ── Pont vers les 5 catégories fines du cross-sell ────────────────────────────
# modules/uc_crosssell/aggregation.py:23-29 garde SA nomenclature (elle sert la
# détection de signaux, pas le calcul de parts). Ce mapping documente la
# correspondance et garantit qu'une même affaire ne soit pas lue « Sécurité »
# d'un côté et « Réseau » de l'autre.
FINE_TO_FAMILY: dict[str, str] = {
    "reseau": "reseau",
    "securite": "logiciel",
    "serveurs_stockage": "equipement",
    "cloud_virtualisation": "logiciel",
    "licences_maintenance": "logiciel",
}


def _normalize(text: str | None) -> str:
    """Minuscules, sans accents, ponctuation réduite à des espaces.

    Le dépouillement des accents évite de doubler chaque entrée du dictionnaire :
    la base Odoo mélange « Réseau », « reseau » et « RESEAU » sur le même marché.
    La ponctuation devient de l'espace pour que « SOC/CIRT », « LOT N°3 : F5 » ou
    « DLP/ Editeur » se découpent en mots — sinon un terme borné ne matcherait
    jamais un acronyme collé à un séparateur.
    """
    if not text:
        return " "
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() or c in "-+" else " " for c in stripped)
    return f" {' '.join(cleaned.split())} "


def _matches(haystack: str, keyword: str) -> bool:
    """Teste un mot-clé contre un libellé normalisé.

    Convention : un mot-clé encadré de « | » exige une correspondance de MOT
    ENTIER (`"|lan|"`), les autres sont cherchés en sous-chaîne. Indispensable
    pour les acronymes courts — sans borne, « lan » matche « pLANification » et
    range « PLAN DE FORMATION » (2 500 M) en Réseau ; « wan » matche « Taïwan »,
    « san » matche « sanction ». Cas réellement rencontrés en base.
    """
    if keyword.startswith("|") and keyword.endswith("|"):
        return f" {keyword.strip('|')} " in haystack
    return keyword in haystack


def classify_family(label: str | None) -> str | None:
    """Famille d'offre déduite d'un libellé d'opportunité, `None` si indécidable.

    `None` n'est pas un échec à masquer : c'est l'information « ce libellé ne dit
    pas ce qu'on vend ». Les appelants doivent le compter et l'exposer comme taux
    de couverture.
    """
    haystack = _normalize(label)
    if haystack.strip() == "":
        return None
    for family, keywords in FAMILY_KEYWORDS:
        if any(_matches(haystack, kw) for kw in keywords):
            return family
    # Dernier recours : un service générique non rattaché à un produit identifié.
    if any(_matches(haystack, kw) for kw in GENERIC_SERVICE_KEYWORDS):
        return "services"
    return None


# Sentinelle de PERSISTANCE : « la taxonomie a tourné sur ce libellé et n'a rien
# pu décider ». À distinguer de NULL en base, qui veut dire « jamais soumis à la
# taxonomie ».
#
# Ce n'est PAS la famille par défaut que le module s'interdit plus haut : elle ne
# range rien nulle part, `label_of("")` rend « Non qualifié » et l'agrégation la
# compte en non-classé exactement comme un None. Elle ne dit que ceci : inutile
# de reclasser cette ligne.
#
# Sans elle, les 4 700 libellés indécidables du miroir (sur 9 475) repassaient
# par `classify_family()` à CHAQUE lecture du mix d'offre pour re-échouer à
# l'identique — 728 000 tests de mots-clés, ~200 ms des 293 ms de l'agrégation
# (profilé le 10/08/2026).
INDECIDABLE = ""


def famille_a_persister(label: str | None) -> str:
    """Valeur de `offer_family` à écrire en base pour ce libellé — jamais NULL.

    À utiliser sur tous les chemins d'écriture (sync Odoo, backfill) ; les
    chemins de LECTURE, eux, appellent `classify_family()` et gardent le `None`
    porteur de sens.
    """
    return classify_family(label) or INDECIDABLE


def family_from_fine_category(fine: str | None) -> str | None:
    """Famille haute correspondant à une catégorie fine du cross-sell."""
    return FINE_TO_FAMILY.get(fine or "")


def label_of(family: str | None) -> str:
    """Libellé d'affichage d'une famille. « Non qualifié » pour l'inclassable."""
    return FAMILY_LABELS.get(family or "", "Non qualifié")
