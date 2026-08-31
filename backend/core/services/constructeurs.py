"""Référentiel constructeur : déduit la MARQUE d'une ligne de commande de son libellé.

Raison d'être : `sale_order_lines.product_code` est vide sur 19 636 des 19 644
lignes du miroir et `product_category` vaut « All » sur 13 992 d'entre elles (défaut
Odoo). Le constructeur n'existe donc nulle part en donnée saisie — uniquement dans
`product_name`, et le plus souvent sous forme de RÉFÉRENCE et non de marque :
`FC-10-0060F-950-02-12`, `FG-100F-BDL-950-12`, `CON-SNT-C8302TNX`, `C9300L-24P-4X-A`.

D'où la mesure qui justifie ce module : `LIKE '%fortinet%'` ne voit que 1 037 M XOF
des 5 661 M réellement vendus en Fortinet — 82 % du chiffre est porté par des lignes
`FC-10-*` et `FG-*-BDL-*` qui n'écrivent jamais « Fortinet ». Symétriquement,
`LIKE '%hp%'` attrapait des lignes Allot et SolarWinds.

Conséquence assumée : le constructeur est une ESTIMATION, pas une donnée saisie. Les
lignes non attribuées sont comptées et EXPOSÉES comme taux de couverture, jamais
rangées dans une marque « Autre » qui les ferait passer pour classées.

Convention de mots-clés reprise de modules/uc_offermix/taxonomy.py, dont ce module
est le pendant pour les marques (l'un classe la FAMILLE d'offre, l'autre le
CONSTRUCTEUR). Les deux primitives `_normalize` / `_matches` y sont volontairement
redupliquées et non importées : `core/` ne dépend pas de `modules/`, et ni `db/` ni
`jobs/` ne doivent dépendre d'aucun des deux.
"""
from __future__ import annotations

import unicodedata

# ── Libellés d'affichage ─────────────────────────────────────────────────────

VENDOR_LABELS: dict[str, str] = {
    "fortinet": "Fortinet",
    "cisco": "Cisco",
    "f5": "F5",
    "checkpoint": "Check Point",
    "paloalto": "Palo Alto",
    "redhat": "Red Hat",
    "vmware": "VMware",
    "veeam": "Veeam",
    "microsoft": "Microsoft",
    "oracle": "Oracle",
    "kaspersky": "Kaspersky",
    "sophos": "Sophos",
    "darktrace": "Darktrace",
    "securite_autre": "Sécurité (autres éditeurs)",
    "supervision": "Supervision (SolarWinds, ManageEngine…)",
    "allot": "Allot",
    "nutanix": "Nutanix",
    "citrix": "Citrix",
    "hpe": "HPE / HP",
    "dell": "Dell",
    "lenovo": "Lenovo",
    "ibm": "IBM",
    "huawei": "Huawei",
    "stockage_nas": "Synology / QNAP / NetApp",
    "energie": "Énergie (APC, Eaton, Vertiv, Legrand)",
    "telephonie": "Téléphonie (Avaya, Polycom, Yealink…)",
    "wifi_reseau_autre": "Réseau (Ruckus, Ubiquiti, MikroTik…)",
    "videosurveillance": "Vidéosurveillance (Axis, Hikvision…)",
    "logiciel_autre": "Logiciel (Adobe, Autodesk, SAP)",
    "impression": "Impression (Zebra, Canon, Epson…)",
    "cablage": "Câblage (Nexans, Panduit, Corning…)",
    "samsung": "Samsung",
    "composants": "Composants (Intel, Kingston, Seagate…)",
}

# ── Règles d'identification ──────────────────────────────────────────────────
#
# LISTE ORDONNÉE, pas un dict : la priorité est signifiante et porte UNE règle
# métier, vérifiée sur le miroir —
#
#   le constructeur du SYSTÈME l'emporte sur celui d'un COMPOSANT qu'il cite.
#
# Les six plus grosses lignes contenant « intel » sont des HP ProDesk et des HPE
# ProLiant : c'est du Xeon dans un serveur HPE, pas une vente Intel. Même chose
# pour « samsung » (barrettes dans un ProLiant) ou « kingston ». D'où les marques
# de composants EN DERNIER : une ligne ne leur revient que si aucun système ne l'a
# revendiquée avant — et alors c'est bien une vente de composant.
#
# Convention (cf. _matches) : un terme encadré de « | » exige un MOT ENTIER, les
# autres sont cherchés en SOUS-CHAÎNE. `_normalize` conserve les tirets, ce qui
# rend les préfixes de référence directement matchables : « fc-10- » retrouve
# FC-10-0060F-950-02-12, que le mot « Fortinet » n'accompagne jamais.
VENDOR_KEYWORDS: list[tuple[str, list[str]]] = [
    # « forti » couvre d'un seul terme fortinet/fortigate/forticare/fortiguard/
    # fortinac/fortiap/fortiswitch/fortianalyzer/fortimail. Les préfixes de
    # référence sont ce qui récupère les 82 % que « fortinet » seul manquait.
    #
    # ATTENTION au tiret de « fap- », il n'est PAS cosmétique : dans ce catalogue
    # « FAP » désigne aussi les Frais d'Approche Portuaire (« FAP - DOUANE »,
    # « FAP Transport et Douanes »), soit 373 M XOF de frais de dédouanement
    # contre 89 M XOF de vrais FortiAP. Écrire « |fap| » attribuerait quatre fois
    # plus de douane que de bornes Wi-Fi à Fortinet. Le tiret sépare les deux
    # parce qu'une référence FortiAP est toujours collée (FAP-231G-E).
    ("fortinet", [
        "forti", "fg-", "fc-10-", "fap-", "fwf-", "faz-", "fml-", "fad-", "fs-1",
    ]),
    # « cisco » en SOUS-CHAÎNE et non borné : les libellés du miroir collent la
    # marque au texte voisin (« CISCO-EQUIPEMENTS », « SHIP NEXT BUS DAYCisco Quad
    # Camera »), qu'un « |cisco| » borné laissait passer.
    # « ise » / « sns-38 » / « stealthwatch » : Identity Services Engine et Secure
    # Network Server, vendus sans que « Cisco » figure au libellé.
    ("cisco", [
        "cisco", "catalyst", "meraki", "webex", "aironet", "|nexus|",
        "con-snt-", "con-ecmu-", "con-snbd-", "con-sssnt-", "ws-c", "air-ap",
        "|ucs|", "a-flex-", "sns-38", "sns-37", "stealthwatch", "|stealth watch|",
        "|ise|", "asr-9", "asr920", "a920-",
        "c9200", "c9300", "c9400", "c9130", "c9120", "c8300", "c8200", "isr4",
        "cbs250", "cbs350", "sg350",
    ]),
    # « f5 » sans borne matcherait n'importe quelle référence contenant f5 ; borné,
    # il ne remonte que du BIG-IP réel (2 209 M XOF, 5e constructeur du miroir).
    ("f5", ["|f5|", "big-ip", "|bigip|"]),
    # « check » seul est un faux positif garanti (« …to check and resolve any
    # incident », 13,5 M XOF) : exiger les deux mots, ou le préfixe CPES-SS-.
    ("checkpoint", ["check-point", "|check point|", "cpes-ss-", "|checkpoint|"]),
    # « pan- » est le préfixe de référence Palo Alto Networks (PAN-PA-3260-ATP-3YR-R,
    # PAN-SVC-PREM-1410-3YR, PAN-PWR-CORD-EU) : il porte 422 M XOF que « palo alto »
    # seul ne voyait pas, la marque n'étant écrite en clair sur aucune de ces lignes.
    ("paloalto", ["palo-alto", "|palo alto|", "|panorama|", "pan-"]),
    ("redhat", ["red hat", "redhat", "openshift", "|rhel|", "rh0000"]),
    ("vmware", ["vmware", "vsphere", "vcenter", "|esxi|", "|nsx|", "vrealize"]),
    ("veeam", ["veeam"]),
    ("microsoft", [
        "microsoft", "|windows|", "|azure|", "office-365", "|office 365|",
        "|m365|", "|o365|", "sharepoint", "|sql server|", "sql-server",
        "exchange-server", "|exchange server|", "|visio|", "power-bi",
    ]),
    ("oracle", ["|oracle|"]),
    ("kaspersky", ["kaspersky"]),
    ("sophos", ["sophos"]),
    # « dartrace » : faute de frappe présente en base sur une ligne à 92 M XOF.
    # Les alias fautifs se traitent ici et non par une correction dans Odoo — le
    # miroir est en lecture seule, et la faute peut se reproduire à la saisie.
    ("darktrace", ["darktrace", "dartrace"]),
    ("securite_autre", [
        "|eset|", "bitdefender", "trend-micro", "|trend micro|", "symantec",
        "mcafee", "|tenable|", "rapid7", "insightvm", "ivm-sub", "|rivm|",
        "qualys", "barracuda", "acronis",
    ]),
    ("supervision", [
        "solarwinds", "|solar winds|", "manageengine", "|manage engine|",
        "|zabbix|", "|nagios|", "|centreon|", "|splunk|",
    ]),
    ("allot", ["|allot|", "acg2000", "acg-"]),
    ("nutanix", ["nutanix"]),
    ("citrix", ["citrix"]),
    ("hpe", [
        "|hpe|", "|hp|", "aruba", "proliant", "prodesk", "elitebook", "elitedesk",
        "probook", "|synergy|", "|msa|", "|nimble|", "|3par|",
    ]),
    ("dell", [
        "|dell|", "poweredge", "powervault", "powerstore", "|emc|", "|idrac|",
        "|vxrail|", "|latitude|", "|optiplex|",
    ]),
    ("lenovo", ["lenovo", "thinkpad", "thinksystem"]),
    ("ibm", ["|ibm|", "|aix|", "|power9|"]),
    # « 0235 » / « 88037 » : préfixes de nomenclature Huawei. Les commutateurs et
    # baies Huawei sont saisis par leur code BOM seul (02355NEH, 02354LMB-002,
    # 88037TSX), la marque n'apparaissant nulle part — 745 M XOF invisibles sans ça.
    # Les familles de modèles servent de second filet si le code BOM manque.
    ("huawei", ["huawei", "0235", "88037", "oceanstor", "|s5755|", "|s6730|", "ce6863"]),
    ("stockage_nas", ["synology", "|qnap|", "netapp"]),
    ("energie", [
        "|apc|", "schneider", "smart-ups", "|eaton|", "|vertiv|", "legrand",
        "|galaxy vs|", "symmetra",
    ]),
    ("telephonie", [
        "|avaya|", "polycom", "yealink", "|unify|", "alcatel", "|mitel|",
        "openscape", "|3cx|",
    ]),
    ("wifi_reseau_autre", [
        "|ruckus|", "ubiquiti", "|unifi|", "mikrotik", "netgear", "|d-link|",
        "|tp-link|", "|extreme networks|", "actiontec",
    ]),
    ("videosurveillance", ["|axis|", "hikvision", "|dahua|", "avigilon", "|milestone|"]),
    ("logiciel_autre", ["|adobe|", "autodesk", "|sap|", "|autocad|"]),
    ("impression", ["|zebra|", "|canon|", "|epson|", "lexmark", "|kyocera|"]),
    ("cablage", ["nexans", "panduit", "corning", "commscope", "|rittal|", "|schroff|"]),
    # ── Composants, EN DERNIER (cf. la règle métier en tête de liste) ────────
    # Samsung est à part : il vend aussi de vrais écrans en direct dans ce
    # catalogue (« SAMSUNG QM98T écran LCD 98 pouces », 12,3 M XOF). Placé ici, il
    # ne capte plus les barrettes citées dans un ProLiant.
    ("samsung", ["samsung"]),
    ("composants", [
        "|intel|", "|amd|", "kingston", "seagate", "western-digital",
        "|micron|", "|crucial|",
    ]),
]


def _normalize(text: str | None) -> str:
    """Minuscules, sans accents, ponctuation réduite à des espaces.

    Les tirets et « + » sont CONSERVÉS : c'est ce qui permet de matcher un préfixe
    de référence (« fc-10- », « con-snt- ») comme sous-chaîne. Sans eux,
    FC-10-0060F-950-02-12 se réduirait à une suite de mots où plus rien
    n'identifierait Fortinet.

    Le padding par espaces des deux côtés rend `_matches` capable de tester un mot
    entier en début et en fin de libellé sans cas particulier.
    """
    if not text:
        return " "
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() or c in "-+" else " " for c in stripped)
    return f" {' '.join(cleaned.split())} "


def _matches(haystack: str, keyword: str) -> bool:
    """Teste un mot-clé contre un libellé normalisé.

    Un mot-clé encadré de « | » exige une correspondance de MOT ENTIER, les autres
    sont cherchés en sous-chaîne. Indispensable pour les sigles courts : « hp »
    sans borne matche un numéro de série (5CG8183HPY) et « f5 » n'importe quelle
    référence ; « intel » borné distingue le processeur du fabricant.
    """
    if keyword.startswith("|") and keyword.endswith("|"):
        return f" {keyword.strip('|')} " in haystack
    return keyword in haystack


def detect_vendor(product_name: str | None, product_code: str | None = None) -> str | None:
    """Constructeur déduit du libellé (et de la référence si elle existe).

    `None` n'est pas un échec à masquer : c'est l'information « ce libellé ne dit
    pas de quelle marque il s'agit » — le cas d'une prestation, d'une ligne de
    frais ou d'un intitulé purement fonctionnel. Les appelants doivent le compter
    et l'exposer comme taux de couverture, jamais le remplacer par une marque.

    `product_code` est concaténé au libellé plutôt que testé à part : il est vide
    sur la quasi-totalité du miroir aujourd'hui, mais une synchro Odoo qui le
    remplirait donnerait le signal le plus fiable — et les mêmes règles s'y
    appliquent, un default_code étant précisément une référence constructeur.
    """
    haystack = _normalize(f"{product_code or ''} {product_name or ''}")
    if haystack.strip() == "":
        return None
    for vendor, keywords in VENDOR_KEYWORDS:
        if any(_matches(haystack, kw) for kw in keywords):
            return vendor
    return None


# Sentinelle de PERSISTANCE : « le référentiel a tourné sur ce libellé et n'a rien
# pu décider ». À distinguer d'une colonne jamais renseignée, qui veut dire « ce
# libellé n'a pas encore été soumis au référentiel » — la distinction est ce qui
# permet à scripts/reclasser_constructeurs.py de ne retraiter que l'utile.
#
# Ce n'est PAS une marque par défaut : `label_of("")` rend « Non attribué » et tout
# agrégat par constructeur doit l'exclure de ses parts de marché.
NON_ATTRIBUE = ""


def vendor_a_persister(product_name: str | None, product_code: str | None = None) -> str:
    """Valeur de `sale_order_lines.vendor` à écrire — jamais NULL.

    À utiliser sur TOUS les chemins d'écriture (synchro Odoo, amorçage local,
    reclassement). Les chemins de LECTURE appellent `detect_vendor()` et gardent
    le `None` porteur de sens.
    """
    return detect_vendor(product_name, product_code) or NON_ATTRIBUE


def label_of(vendor: str | None) -> str:
    """Libellé d'affichage d'un constructeur. « Non attribué » pour l'indécidable."""
    return VENDOR_LABELS.get(vendor or "", "Non attribué")
