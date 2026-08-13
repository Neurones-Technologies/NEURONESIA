"""Marché : axes stratégiques, secteurs, part de marché, veille — §1 et §4 du CR.

« Évaluer les tendances : part du marché et selon aussi la santé du marché orienté
(Ex : Intelligence Artificielle et infrastructure…) » et « Tendance des secteurs :
performance commerciale ventilée par secteur d'activité ».

Trois demandes, trois régimes de faisabilité très différents — et c'est le point
que cet écran doit rendre évident :

1. AXES STRATÉGIQUES : MESURABLE. « IA », « infrastructure », « cloud » n'existent
   nulle part dans le CRM, mais les LIBELLÉS d'opportunité les nomment. Une grille
   de motifs éditable (`strategic_axis_mappings`) suffit à ventiler le pipe réel.
   C'est le seul des trois qui répond vraiment à « la santé du marché orienté IA
   et infrastructure », et il le fait sur nos affaires — pas sur le marché.

   Cette grille est DISTINCTE de la taxonomie de familles d'offre (uc_offermix) :
   celle-ci répond à « qu'est-ce qu'on vend » (logiciel/réseau/équipement/services),
   celle-là à « sur quel marché ». Un même équipement peut relever de l'axe
   datacenter ou de l'axe cybersécurité selon le projet.

2. SECTEURS : NON MESURABLE aujourd'hui. `clients.sector` est renseigné pour 1
   client sur 1 508. Le gabarit sert à faire valider la NOMENCLATURE, puisque
   c'est elle qui déterminera la saisie à mener.

3. PART DE MARCHÉ : NON MESURABLE, et pour une raison qui ne se corrigera pas par
   la saisie — il manque un univers de référence externe. Ce qui est calculable
   sans source externe, c'est la part de NOTRE portefeuille. Les deux sont servis
   côte à côte, nommés différemment, parce que les confondre conduit à des
   décisions erronées.
"""
from __future__ import annotations

import unicodedata

from modules.uc_commercial import statique
from modules.uc_commercial.comptes import est_ouverte

# Grille de lecture par défaut, semée en base au premier appel puis éditable.
# L'ordre de `priority` compte : « intelligence artificielle » doit gagner sur
# « data » pour un libellé qui contient les deux, sinon l'axe IA reste vide.
AXES_DEFAUT: list[dict] = [
    {"axe": "Intelligence artificielle", "pattern": "intelligence artificielle", "priority": 10},
    {"axe": "Intelligence artificielle", "pattern": " ia ", "priority": 11},
    {"axe": "Intelligence artificielle", "pattern": "machine learning", "priority": 12},
    {"axe": "Intelligence artificielle", "pattern": "chatbot", "priority": 13},
    {"axe": "Cybersécurité", "pattern": "securit", "priority": 20},
    {"axe": "Cybersécurité", "pattern": "securisation", "priority": 20},
    {"axe": "Cybersécurité", "pattern": "firewall", "priority": 21},
    {"axe": "Cybersécurité", "pattern": "antivirus", "priority": 22},
    {"axe": "Cybersécurité", "pattern": "soc", "priority": 23},
    # Éditeurs et gammes : sur ce pipe, l'axe se lit plus souvent au nom du
    # produit qu'au nom du besoin (« WALLIX », « Darktrace », « FortiGate »).
    # Sans ces motifs, 45 % du pipe restait non qualifiable.
    {"axe": "Cybersécurité", "pattern": "forti", "priority": 24},
    {"axe": "Cybersécurité", "pattern": "wallix", "priority": 24},
    {"axe": "Cybersécurité", "pattern": "darktrace", "priority": 24},
    {"axe": "Cybersécurité", "pattern": "symantec", "priority": 24},
    {"axe": "Cybersécurité", "pattern": "varonis", "priority": 24},
    {"axe": "Cybersécurité", "pattern": "kaspersky", "priority": 24},
    {"axe": "Cybersécurité", "pattern": "trend micro", "priority": 24},
    {"axe": "Cybersécurité", "pattern": " dlp ", "priority": 25},
    {"axe": "Cybersécurité", "pattern": " dns ", "priority": 25},
    {"axe": "Cybersécurité", "pattern": " pra ", "priority": 26},
    {"axe": "Cybersécurité", "pattern": " pca ", "priority": 26},
    {"axe": "Cloud et hébergement", "pattern": "cloud", "priority": 30},
    {"axe": "Cloud et hébergement", "pattern": "hebergement", "priority": 31},
    {"axe": "Cloud et hébergement", "pattern": "saas", "priority": 32},
    {"axe": "Cloud et hébergement", "pattern": "azure", "priority": 33},
    {"axe": "Cloud et hébergement", "pattern": "o365", "priority": 33},
    {"axe": "Cloud et hébergement", "pattern": "office 365", "priority": 33},
    {"axe": "Cloud et hébergement", "pattern": "microsoft 365", "priority": 33},
    {"axe": "Infrastructure et datacenter", "pattern": "datacenter", "priority": 40},
    # « data center » en deux mots doit être capté AVANT le motif « data » de l'axe
    # Données (priorité 60), sans quoi un projet de salle machine se retrouve
    # classé en décisionnel — cas observé sur ce pipe.
    {"axe": "Infrastructure et datacenter", "pattern": "data center", "priority": 40},
    {"axe": "Infrastructure et datacenter", "pattern": "serveur", "priority": 41},
    {"axe": "Infrastructure et datacenter", "pattern": "stockage", "priority": 42},
    {"axe": "Infrastructure et datacenter", "pattern": "onduleur", "priority": 43},
    {"axe": "Infrastructure et datacenter", "pattern": "climatisation", "priority": 44},
    {"axe": "Infrastructure et datacenter", "pattern": "sauvegarde", "priority": 45},
    {"axe": "Infrastructure et datacenter", "pattern": "virtualisation", "priority": 46},
    {"axe": "Réseau et télécom", "pattern": "reseau", "priority": 50},
    {"axe": "Réseau et télécom", "pattern": "network", "priority": 50},
    {"axe": "Réseau et télécom", "pattern": "switch", "priority": 51},
    {"axe": "Réseau et télécom", "pattern": "wifi", "priority": 52},
    {"axe": "Réseau et télécom", "pattern": "fibre", "priority": 53},
    {"axe": "Réseau et télécom", "pattern": "cablage", "priority": 53},
    {"axe": "Réseau et télécom", "pattern": "telephonie", "priority": 54},
    {"axe": "Réseau et télécom", "pattern": " wan", "priority": 55},
    {"axe": "Réseau et télécom", "pattern": "sdwan", "priority": 55},
    {"axe": "Réseau et télécom", "pattern": " lan ", "priority": 55},
    {"axe": "Réseau et télécom", "pattern": "cisco", "priority": 56},
    {"axe": "Réseau et télécom", "pattern": "routeur", "priority": 56},
    {"axe": "Réseau et télécom", "pattern": "voip", "priority": 57},
    {"axe": "Réseau et télécom", "pattern": "volte", "priority": 57},
    {"axe": "Réseau et télécom", "pattern": " ims ", "priority": 57},
    {"axe": "Réseau et télécom", "pattern": " sbc ", "priority": 57},
    {"axe": "Collaboration et visioconférence", "pattern": "visio", "priority": 58},
    {"axe": "Collaboration et visioconférence", "pattern": "conference", "priority": 58},
    {"axe": "Collaboration et visioconférence", "pattern": "collaboration", "priority": 58},
    {"axe": "Collaboration et visioconférence", "pattern": "teams", "priority": 59},
    {"axe": "Données et décisionnel", "pattern": "data", "priority": 60},
    {"axe": "Données et décisionnel", "pattern": "decisionnel", "priority": 61},
    {"axe": "Données et décisionnel", "pattern": "reporting", "priority": 62},
    {"axe": "Applicatif et gestion", "pattern": "erp", "priority": 70},
    {"axe": "Applicatif et gestion", "pattern": "application", "priority": 71},
    {"axe": "Applicatif et gestion", "pattern": "logiciel", "priority": 72},
    {"axe": "Applicatif et gestion", "pattern": "licence", "priority": 73},
    {"axe": "Poste de travail", "pattern": "poste de travail", "priority": 80},
    {"axe": "Poste de travail", "pattern": "ordinateur", "priority": 81},
    {"axe": "Poste de travail", "pattern": "imprimante", "priority": 82},
    {"axe": "Poste de travail", "pattern": "laptop", "priority": 83},
    {"axe": "Poste de travail", "pattern": "desktop", "priority": 83},
    {"axe": "Poste de travail", "pattern": "dell", "priority": 84},
    {"axe": "Services et accompagnement", "pattern": "formation", "priority": 90},
    {"axe": "Services et accompagnement", "pattern": "maintenance", "priority": 91},
    {"axe": "Services et accompagnement", "pattern": "assistance", "priority": 92},
    {"axe": "Services et accompagnement", "pattern": "audit", "priority": 93},
    {"axe": "Services et accompagnement", "pattern": "supervision", "priority": 94},
    {"axe": "Services et accompagnement", "pattern": "infogerance", "priority": 94},
    # Motifs de repli, en DERNIÈRE priorité : ils n'ont de sens qu'une fois tous
    # les motifs spécifiques testés. « matériel informatique » sans autre indice
    # relève de l'infrastructure ; placé plus haut, il capterait des serveurs et
    # des switchs qui ont leur propre axe.
    {"axe": "Infrastructure et datacenter", "pattern": "materiel informatique", "priority": 200},
    {"axe": "Infrastructure et datacenter", "pattern": "equipement informatique", "priority": 200},
    {"axe": "Infrastructure et datacenter", "pattern": "infrastructure", "priority": 201},
]

AXE_NON_CLASSE = "Non qualifiable"


def _normalise(texte: str | None) -> str:
    """Minuscules, sans accent, espaces réduits — et ENCADRÉ d'espaces.

    L'encadrement permet aux motifs courts (« ia », « soc ») d'être cherchés comme
    des mots entiers : sans lui, « ia » se déclencherait sur « spécialisation » et
    l'axe IA serait faux d'un facteur dix.
    """
    if not texte:
        return " "
    d = unicodedata.normalize("NFKD", str(texte).lower())
    sans_accent = "".join(c for c in d if not unicodedata.combining(c))
    return " " + " ".join(sans_accent.replace("-", " ").replace("/", " ").split()) + " "


def classer_axe(libelle: str | None, mappings: list[dict]) -> str:
    """Premier motif qui matche, dans l'ordre de priorité. `AXE_NON_CLASSE` sinon."""
    texte = _normalise(libelle)
    for m in sorted(mappings, key=lambda x: x.get("priority", 100)):
        motif = _normalise(m["pattern"]).strip()
        if not motif:
            continue
        # Un motif encadré d'espaces dans la grille (« ia ») cherche un mot entier ;
        # sinon la sous-chaîne suffit (« securit » attrape sécurité et sécurisation).
        cible = f" {motif} " if m["pattern"].startswith(" ") or len(motif) <= 3 else motif
        if cible in texte:
            return m["axe"]
    return AXE_NON_CLASSE


def build_axes_strategiques(opportunites: list[dict], mappings: list[dict]) -> dict:
    """Ventilation MESURÉE du pipe et des affaires closes par axe de marché."""
    grille = mappings or AXES_DEFAUT
    par_axe: dict[str, dict] = {}

    for o in opportunites:
        axe = classer_axe(o.get("name"), grille)
        a = par_axe.setdefault(axe, {
            "axe": axe, "nb_ouvertes": 0, "montant_ouvert_xof": 0, "montant_pondere_xof": 0,
            "nb_gagnees": 0, "montant_gagne_xof": 0, "nb_perdues": 0, "montant_perdu_xof": 0,
        })
        montant = o.get("montant_xof", 0)
        etape = (o.get("stage") or "").lower()
        if est_ouverte(etape):
            a["nb_ouvertes"] += 1
            a["montant_ouvert_xof"] += montant
            a["montant_pondere_xof"] += montant * (o.get("probabilite_pct", 0) / 100)
        elif any(p in etape for p in ("gagn", "won")):
            a["nb_gagnees"] += 1
            a["montant_gagne_xof"] += montant
        elif any(p in etape for p in ("perdu", "lost")):
            a["nb_perdues"] += 1
            a["montant_perdu_xof"] += montant

    classes = [a for cle, a in par_axe.items() if cle != AXE_NON_CLASSE]
    non_classe = par_axe.get(AXE_NON_CLASSE, {
        "nb_ouvertes": 0, "montant_ouvert_xof": 0, "nb_gagnees": 0, "nb_perdues": 0,
        "montant_gagne_xof": 0, "montant_perdu_xof": 0, "montant_pondere_xof": 0,
    })
    total_classe = sum(a["montant_ouvert_xof"] for a in classes)
    total_ouvert = total_classe + non_classe["montant_ouvert_xof"]

    for a in classes:
        engage = a["montant_gagne_xof"] + a["montant_perdu_xof"]
        a["montant_pondere_xof"] = round(a["montant_pondere_xof"])
        a["part_montant_pct"] = round(100 * a["montant_ouvert_xof"] / total_classe, 1) if total_classe else 0.0
        a["win_rate_pct"] = round(100 * a["montant_gagne_xof"] / engage, 1) if engage else None
        a["nb_closes"] = a["nb_gagnees"] + a["nb_perdues"]
    classes.sort(key=lambda a: -a["montant_ouvert_xof"])

    return {
        "source": statique.SOURCE_REELLE,
        "axes": classes,
        "coverage": {
            "nb_non_classe": non_classe["nb_ouvertes"],
            "montant_non_classe_xof": non_classe["montant_ouvert_xof"],
            "couverture_montant_pct": round(100 * total_classe / total_ouvert, 1) if total_ouvert else 0.0,
            "nb_motifs": len(grille),
            "nb_axes": len(classes),
        },
        "dominante": classes[0] if classes else None,
        "note": (
            "Axe déduit du LIBELLÉ de l'opportunité au moyen d'une grille de motifs éditable — le CRM ne "
            "porte aucune notion d'axe de marché. Les parts portent sur le pipe classé, jamais sur le pipe "
            "total : le taux de couverture est affiché avec elles. Cette grille est une convention de "
            "lecture, pas une donnée extraite : la corriger fait bouger les chiffres, ce qui est normal."
        ),
    }


def build_secteurs(couverture_secteur: dict) -> dict:
    """Performance par secteur — GABARIT, avec la couverture RÉELLE en regard.

    Les deux blocs sont servis ensemble volontairement : le gabarit montre la
    forme et propose une nomenclature, la couverture dit pourquoi il n'est pas
    alimenté. Servir l'un sans l'autre serait soit incompréhensible, soit trompeur.
    """
    secteurs = [dict(s) for s in statique.SECTEURS_STATIQUES]
    total_ca = sum(s["ca_xof"] for s in secteurs)
    for s in secteurs:
        s["part_ca_pct"] = round(100 * s["ca_xof"] / total_ca, 1) if total_ca else 0.0
        s["part_marche_pct"] = round(100 * s["ca_xof"] / s["taille_marche_xof"], 2) if s["taille_marche_xof"] else None
    secteurs.sort(key=lambda s: -s["ca_xof"])

    taille_totale = sum(s["taille_marche_xof"] for s in secteurs)
    return {
        "source": statique.SOURCE_STATIQUE,
        "raison": statique.RAISON_SECTEUR_STATIQUE,
        "avertissement": statique.AVERTISSEMENT_STATIQUE,
        "secteurs": secteurs,
        "totaux": {
            "ca_xof": total_ca,
            "nb_clients": sum(s["nb_clients"] for s in secteurs),
            "taille_marche_xof": taille_totale,
            "part_marche_globale_pct": round(100 * total_ca / taille_totale, 2) if taille_totale else None,
        },
        "part_marche": {
            "source": statique.SOURCE_STATIQUE,
            "raison": statique.RAISON_PART_MARCHE_STATIQUE,
            "distinction": (
                "Part de MARCHÉ = notre CA rapporté à la taille du marché adressable, impossible à "
                "calculer sans source externe. Part de PORTEFEUILLE = notre CA rapporté à notre propre "
                "total, calculable dès aujourd'hui. Les deux ne se substituent pas."
            ),
        },
        "couverture_reelle": {
            **couverture_secteur,
            "verdict": (
                f"{couverture_secteur.get('nb_avec_secteur', 0)} client(s) sur "
                f"{couverture_secteur.get('nb_clients', 0)} portent un secteur d'activité : l'analyse "
                "sectorielle réelle reste impossible tant que ce champ n'est pas renseigné, quel que "
                "soit le développement réalisé."
            ),
        },
    }


def build_veille(veille: dict, limit: int = 12) -> dict:
    """Signaux de marché externes réellement collectés, avec leur taux de déchet.

    Les entrées sans URL sont écartées des signaux servis : ce sont des libellés de
    menu capturés par le scraper, pas des annonces. Elles restent comptées dans
    `qualite` — une veille dont on ne dit pas le taux de déchet se lirait comme un
    panorama de marché, ce qu'elle n'est pas encore.
    """
    entrees = [e for e in veille.get("entrees", []) if e.get("url")]
    entrees.sort(key=lambda e: (-e.get("criticite", 0), e.get("detecte_le") or ""))
    qualite = veille.get("qualite", {})
    total = qualite.get("nb_total", 0)
    exploitables = qualite.get("nb_avec_url", 0)
    return {
        "source": statique.SOURCE_REELLE,
        "signaux": entrees[:limit],
        "sources": veille.get("sources", []),
        "qualite": {
            **qualite,
            "part_exploitable_pct": round(100 * exploitables / total, 1) if total else 0.0,
        },
        "note": (
            "Signaux collectés sur les portails d'appels d'offres publics (marchés publics ivoiriens, "
            "bailleurs régionaux). Les entrées sans lien sont du bruit de collecte — libellés de menu "
            "capturés comme titres — et ne sont pas servies comme signaux. Aucune date de publication "
            "n'est remontée par les sources actuelles : l'ancienneté d'un signal n'est donc pas connue, "
            "seule sa date de détection l'est."
        ),
    }
