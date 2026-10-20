"""Entités du groupe et règles de rattachement d'un objet à un pays.

Le pays d'une AFFAIRE est celui de sa commande nt360 (`?entite=`, 100 % des
commandes) : c'est le pivot, rejoint par N° FP. Les autres liens ne sont que des
REPLIS, essayés dans un ordre fixe quand le pivot ne répond pas ; au-delà, on ne
devine pas — l'objet est « non rattaché » et compté comme tel.

`entite_source` dit quelle règle a donné le pays, pour que tout chiffre par pays
reste vérifiable :
    nt360         entité publiée par nt360 (commandes)
    filiale       champ `filiale` nt360 (factures, BC, consultations)
    commande_fp   pays de la commande de même N° FP
    facture       facture nt360 de même numéro (créances Odoo)
    dossier_dc    factures / BC nt360 portant le même N° DC (un seul pays)
    equipe        équipe commerciale Odoo désignant un pays (Sales CIV / BF / GN)
    commercial    commercial n'ayant vendu que dans ce pays sur 24 mois
    ""            non rattaché
"""

ENTITES = ("CI", "BF", "GN")

# Équipes commerciales Odoo (crm.team) qui désignent un pays. Les équipes
# FONCTIONNELLES — BU, BU CLOUD ET SERVICES MANAGES, BU FORMATION, Sales AM,
# Sales, Europe, Point of Sale, Website — n'en désignent aucun : leurs commandes
# sont à 99 % ivoiriennes, mais aussi burkinabées ou guinéennes. Elles ne
# rattachent donc rien (relevé Odoo du 2026-10-19 : une seule société, les pays
# n'existent qu'à travers ces équipes).
EQUIPES_PAYS: dict[str, str] = {
    "Sales CIV": "CI",
    "Sales BF": "BF",
    "Vente BF": "BF",
    "Sales GN": "GN",
}

# Fenêtre de la règle « commercial mono-pays » : l'affectation ACTUELLE d'un
# commercial, pas tout son historique (un commercial muté de CI vers BF il y a
# trois ans ne doit pas rester « multi-pays » pour toujours).
FENETRE_COMMERCIAL_MOIS = 24


def sql_equipe_vers_pays(colonne: str) -> str:
    """CASE SQL : équipe Odoo → pays, NULL pour une équipe fonctionnelle.
    Généré depuis EQUIPES_PAYS pour qu'une seule table fasse foi (Python et vues)."""
    branches = " ".join(
        f"WHEN '{equipe}' THEN '{pays}'" for equipe, pays in EQUIPES_PAYS.items()
    )
    return f"(CASE TRIM({colonne}) {branches} END)"
