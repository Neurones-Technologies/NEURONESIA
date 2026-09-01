"""Tests du référentiel constructeur : identification de la marque par le libellé.

Aucun cas n'est décoratif : chacun correspond à un piège rencontré sur les
19 510 lignes réelles du miroir, et les libellés sont réels ou directement dérivés
de libellés réels. Ce fichier est là pour qu'une « simplification » des règles
casse un test au lieu de fausser silencieusement un chiffre d'affaires.
"""
from core.services.constructeurs import (
    NON_ATTRIBUE,
    VENDOR_KEYWORDS,
    detect_vendor,
    label_of,
    vendor_a_persister,
)


# ── Le piège qui justifie ce module : la marque n'est pas dans le libellé ─────

def test_reference_sans_la_marque():
    """82 % du CA Fortinet est porté par des références qui n'écrivent jamais
    « Fortinet » : c'est la raison d'être du référentiel. Un `LIKE '%fortinet%'`
    ne voyait que 1 037 M XOF sur 5 661 M."""
    assert detect_vendor("FC-10-0060F-950-02-12 FortiGate-60F 1 Year UTP") == "fortinet"
    assert detect_vendor("FG-100F 22 x GE RJ45 ports (including 2 x WAN)") == "fortinet"
    assert detect_vendor("FAP-231G-E FortiAP-231G Indoor Wireless AP") == "fortinet"
    # Cisco : contrats de support et références de châssis, sans la marque.
    assert detect_vendor("CON-SNT-C8302TNX SNTC-8X5XNBD") == "cisco"
    assert detect_vendor("C9300L-24P-4X-A 24P PoE Network Advantage") == "cisco"
    assert detect_vendor("A-FLEX-SRST-E SRST Endpoints (1)") == "cisco"
    assert detect_vendor("SNS-3815-K9 Small Secure Network Server") == "cisco"
    # Palo Alto : le préfixe PAN- porte 422 M XOF, la marque n'est écrite nulle part.
    assert detect_vendor("PAN-SVC-PREM-1410-3YR Premium support, 3 years") == "paloalto"
    # Huawei : saisi par code BOM seul.
    assert detect_vendor("02355NEH S5755-H48UN4Y2CZ (48*10/100/1000 ports)") == "huawei"


def test_fap_douane_nest_pas_fortiap():
    """« FAP » désigne AUSSI les Frais d'Approche Portuaire dans ce catalogue :
    373 M XOF de dédouanement contre 89 M XOF de vrais FortiAP. Le tiret de
    « fap- » est ce qui sépare les deux — le relâcher en « |fap| » attribuerait
    quatre fois plus de douane que de bornes Wi-Fi à Fortinet."""
    assert detect_vendor("FAP - DOUANE") is None
    assert detect_vendor("FAP Transport et Douanes") is None
    assert detect_vendor('FAP "- Transport - Douane - Livraison"') is None
    # …tandis que la vraie référence FortiAP, elle, est toujours collée.
    assert detect_vendor("FAP-441K-E FortiAP-441K Indoor Wireless AP") == "fortinet"


def test_marque_collee_au_texte_voisin():
    """Les libellés du miroir collent la marque au mot suivant. Un « |cisco| »
    borné laissait passer 226 M XOF, dont « CISCO-EQUIPEMENTS » à 221,8 M."""
    assert detect_vendor("CISCO-EQUIPEMENTS") == "cisco"
    assert detect_vendor("CON-SNBD-CSQUAD1C SHIP NEXT BUS DAYCisco Quad Camera") == "cisco"


# ── La règle d'ordre : le système avant le composant ──────────────────────────

def test_systeme_prime_sur_composant():
    """Les six plus grosses lignes contenant « intel » sont des HP ProDesk et des
    HPE ProLiant : c'est du Xeon DANS un serveur, pas une vente Intel. Sans cet
    ordre, 585 M XOF de serveurs HPE et Dell basculeraient en « Composants »."""
    assert detect_vendor("1 x HPE ProLiant DL380 Gen10 + 2 x Intel Xeon Silver 4208") == "hpe"
    assert detect_vendor("6EF24AV HP ProDesk 400 G6 SFF PC Intel Pentium") == "hpe"
    assert detect_vendor("Dell PowerEdge R740 Intel Xeon Gold") == "dell"
    assert detect_vendor("HPE ProLiant DL380 2 x Intel Xeon + 4 x Samsung 32Go") == "hpe"


def test_composant_vendu_seul_reste_un_composant():
    """La contrepartie de l'ordre : une ligne qu'aucun système ne revendique EST
    une vente de composant, et doit être classée comme telle."""
    assert detect_vendor("KTH-PL429/32G Kingston 32Go DDR4 2933MHz") == "composants"
    assert detect_vendor("Disque dur Seagate IronWolf ST8000VN0022") == "composants"
    # Samsung vend aussi de vrais écrans en direct dans ce catalogue.
    assert detect_vendor("SAMSUNG QM98T QMT series ecran LCD 4K UHD") == "samsung"


# ── Faux positifs : les bornes de mot ─────────────────────────────────────────

def test_sigles_courts_bornes():
    """« check » sans son second mot matche « …to check and resolve any incident »
    (13,5 M XOF). « hp » sans borne matche un numéro de série. Les deux étaient
    des faux positifs réels de l'approche par LIKE."""
    assert detect_vendor("managed service support when requested to check and resolve") is None
    assert detect_vendor("CPES-SS-PREMIUM Check Point Direct Enterprise") == "checkpoint"
    assert detect_vendor("HP Elitebook 840 G3 / SN : 5CG8183HRY") == "hpe"
    # Allot et SolarWinds étaient attrapés par `LIKE '%hp%'`.
    assert detect_vendor("W1-ACG2000-1G Allot ACG2000 Series Bundle 1Gbps") == "allot"
    assert detect_vendor("SolarWinds Network Performance Monitor SLX") == "supervision"


def test_alias_fautif():
    """Le miroir porte « DARTRACE » sur une ligne à 92 M XOF. Les fautes de saisie
    se traitent dans le référentiel : Odoo est la source et reste intouché."""
    assert detect_vendor("DARTRACE SOLUTION") == "darktrace"
    assert detect_vendor("Darktrace Enterprise Immune System") == "darktrace"


# ── La doctrine du non-attribué ───────────────────────────────────────────────

def test_non_attribue_nest_pas_une_marque():
    """`None` porte une information : « ce libellé ne dit pas de quelle marque il
    s'agit ». Ne JAMAIS le remplacer par une marque « Autre » — 24 140 M XOF de
    prestations et de lots d'appel d'offres passeraient pour classés."""
    assert detect_vendor("Prestation de mise en oeuvre et transfert de competences") is None
    assert detect_vendor("Access Switches Modular 5x48 ports") is None
    assert detect_vendor("SERVICE PROFESSIONNEL") is None
    assert detect_vendor("") is None
    assert detect_vendor(None) is None
    assert label_of(None) == "Non attribué"
    assert label_of("") == "Non attribué"


def test_valeur_persistee_jamais_nulle():
    """Les chemins d'ÉCRITURE persistent la sentinelle "" (le référentiel a tourné
    sans trancher), à distinguer d'une colonne jamais renseignée. Les chemins de
    LECTURE gardent le None porteur de sens."""
    assert vendor_a_persister("Prestation de mise en oeuvre") == NON_ATTRIBUE
    assert vendor_a_persister(None) == NON_ATTRIBUE
    assert vendor_a_persister("FG-100F 22 x GE RJ45 ports") == "fortinet"


def test_product_code_pris_en_compte():
    """`product_code` est vide sur la quasi-totalité du miroir, mais une synchro
    Odoo qui le remplirait donnerait le signal le plus fiable — un default_code
    EST une référence constructeur."""
    assert detect_vendor("Pare-feu 60 utilisateurs", "FG-60F-BDL-950-12") == "fortinet"
    assert detect_vendor("Commutateur 48 ports", "C9300-48P-A") == "cisco"


# ── Intégrité du référentiel lui-même ─────────────────────────────────────────

def test_pas_de_marque_en_double():
    """Une marque présente deux fois rendrait la seconde entrée morte, la première
    gagnant toujours — et le silence de ce doublon coûterait un CA entier."""
    marques = [v for v, _ in VENDOR_KEYWORDS]
    assert len(marques) == len(set(marques))


def test_toute_marque_a_un_libelle():
    """Une marque sans libellé s'afficherait « Non attribué » dans les restitutions
    tout en étant, en base, parfaitement classée : l'incohérence la plus coûteuse
    à diagnostiquer."""
    for vendor, _ in VENDOR_KEYWORDS:
        assert label_of(vendor) != "Non attribué", vendor


def test_composants_en_dernier():
    """L'ordre porte la règle métier « le système prime sur le composant ». Le
    vérifier explicitement : un ajout de marque en fin de liste casserait
    l'invariant sans casser aucun autre test."""
    marques = [v for v, _ in VENDOR_KEYWORDS]
    assert marques[-1] == "composants"
    assert marques.index("samsung") == len(marques) - 2
    for systeme in ("hpe", "dell", "cisco", "fortinet"):
        assert marques.index(systeme) < marques.index("composants")
