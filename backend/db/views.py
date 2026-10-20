"""Vues de lecture : commandes nt360 détaillées par les lignes Odoo.

nt360 est la RÉFÉRENCE des commandes : quelles commandes existent, leur
montant HT (`cas`), leur client, leur commercial, leur BU. Odoo n'apporte que
le DÉTAIL — les lignes produit (constructeur, catégorie, quantités) — des
commandes que nt360 connaît. Une commande Odoo absente de nt360 n'apparaît dans
aucune de ces vues.

Jointure : nt360_commandes.fp = sale_orders.name (unique côté Odoo) →
sale_order_lines.order_id.

Invariant des vues : pour chaque FP, Σ v_lignes_commande.montant_ht =
v_commandes.montant_ht = cas nt360. C'est ce qui garantit qu'une ventilation
par constructeur ou par catégorie retombe sur le total nt360.

Pour tenir l'invariant quand le total des lignes Odoo diffère du `cas` (écart
médian 5 % au premier rapprochement, typiquement un taux de change différent
sur une commande en devise) :

- RECALAGE (cas courant) : chaque ligne est multipliée par cas / Σ lignes. La
  ventilation entre produits reste celle d'Odoo, le total devient celui de nt360.
  Autorisé tant que le coefficient reste dans [0 ; 2] — au-delà, l'écart ne
  ressemble plus à un taux de change et le répartir déformerait les parts.
- AJUSTEMENT (repli) : sans ligne exploitable (FP absent d'Odoo, commande sans
  ligne, total ≤ 0, coefficient > 2), les lignes Odoo gardent leur montant et
  une ligne « non détaillé » (vendor vide) porte la différence. Elle reste
  hors de toute part de marché, comme une ligne dont le constructeur est inconnu.

Les vues sont recréées à chaque démarrage (DROP + CREATE) : modifier une
définition ici suffit, sans migration.
"""
import logging
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.services.entites import FENETRE_COMMERCIAL_MOIS, sql_equipe_vers_pays

logger = logging.getLogger(__name__)

# Coefficient de recalage maximal ; au-delà → ligne d'ajustement.
COEF_MAX = 2.0

# ── Rattachement par pays : pivots ───────────────────────────────────────────
# Règles et vocabulaire de `entite_source` : core/services/entites.py. Chaque vue
# métier prend le PREMIER lien qui répond, dans un ordre fixe ; au-delà, « non
# rattaché » (entite = '') — jamais deviné, toujours compté.

# Pivot : le pays d'une affaire est celui de sa commande nt360 (100 % des
# commandes portent leur entité). Toutes les vues le rejoignent par N° FP.
_V_ENTITE_FP = """
CREATE VIEW v_entite_fp AS
SELECT fp, entite FROM nt360_commandes WHERE entite != ''
"""

# Repli « commercial mono-pays » : un commercial qui n'a vendu que dans un pays
# sur la fenêtre récente → ce pays. Un commercial présent dans plusieurs pays ne
# rattache RIEN (63 opportunités ouvertes au premier relevé) : choisir son pays
# majoritaire serait deviner.
_V_ENTITE_COMMERCIAL = f"""
CREATE VIEW v_entite_commercial AS
SELECT UPPER(TRIM(am)) AS am, MAX(entite) AS entite
FROM nt360_commandes
WHERE am != '' AND entite != ''
  AND date_commande >= date('now', '-{FENETRE_COMMERCIAL_MOIS} months')
GROUP BY UPPER(TRIM(am))
HAVING COUNT(DISTINCT entite) = 1
"""

# Repli « N° DC » pour les dossiers : pays des factures et BC nt360 qui portent
# ce N° DC (facture : filiale puis commande ; BC : commande puis filiale). Un DC
# dont les pièces désignent plusieurs pays n'est pas rattaché.
_V_ENTITE_DC = """
CREATE VIEW v_entite_dc AS
SELECT dc, MAX(entite) AS entite FROM (
    SELECT f.dc, COALESCE(NULLIF(f.filiale, ''), e.entite) AS entite
    FROM nt360_factures f LEFT JOIN v_entite_fp e ON e.fp = f.fp
    WHERE f.dc != ''
    UNION ALL
    SELECT b.dc, COALESCE(e.entite, NULLIF(b.filiale, '')) AS entite
    FROM nt360_bc b LEFT JOIN v_entite_fp e ON e.fp = b.fp
    WHERE b.dc != ''
)
WHERE entite IS NOT NULL
GROUP BY dc
HAVING COUNT(DISTINCT entite) = 1
"""

_V_COMMANDES = f"""
CREATE VIEW v_commandes AS
WITH lignes AS (
    SELECT order_id, SUM(subtotal_xof) AS total
    FROM sale_order_lines
    WHERE display_type IS NULL
    GROUP BY order_id
),
base AS (
    SELECT n.*, s.order_id, s.client_id, s.dossier_id, s.state AS state_odoo,
           s.amount_untaxed AS montant_ht_odoo, lignes.total AS total_lignes_odoo,
           (lignes.total > 0 AND n.cas >= 0 AND n.cas <= {COEF_MAX} * lignes.total) AS recalable
    FROM nt360_commandes n
    LEFT JOIN sale_orders s ON s.name = n.fp
    LEFT JOIN lignes ON lignes.order_id = s.order_id
)
SELECT
    fp,
    entite,
    CASE WHEN entite != '' THEN 'nt360' ELSE '' END AS entite_source,
    client AS client_name,
    affaire,
    bu,
    am AS salesperson_name,
    pm,
    sales_team,
    cas AS montant_ht,
    facture AS facture_ht,
    raf AS raf_ht,
    year_po,
    date_commande,
    date_demarrage,
    date_contractuelle,
    date_fin_prev,
    couverture,
    synced_at,
    json_extract(raw, '$.dateEcriture') AS date_ecriture,
    order_id,
    client_id,
    dossier_id,
    state_odoo,
    montant_ht_odoo,
    total_lignes_odoo,
    CASE WHEN recalable THEN cas / total_lignes_odoo ELSE 1.0 END AS coefficient,
    CASE WHEN recalable THEN 0.0 ELSE cas - COALESCE(total_lignes_odoo, 0) END AS ajustement,
    CASE
        WHEN order_id IS NULL THEN 'absente_odoo'
        WHEN COALESCE(total_lignes_odoo, 0) = 0 THEN 'sans_lignes'
        WHEN ABS(cas - total_lignes_odoo) <= 1 THEN 'conforme'
        WHEN recalable THEN 'recalee'
        ELSE 'ajustee'
    END AS rapprochement
FROM base
"""

# Date au format DateTime de SQLAlchemy/SQLite : les lecteurs existants lisent
# `date_order` comme un DATETIME (extract, strftime, comparaisons de chaînes).
# Ordre : date de commande nt360, sinon Odoo, sinon une date DANS l'exercice
# nt360 (`year_po`) — la date d'écriture nt360 si elle y tombe, à défaut le
# 31/12. Sans ce dernier repli, 10 commandes sans date ni contrepartie Odoo
# (55 M en 2026) sortaient de tout filtre par année et les totaux annuels ne
# retombaient plus sur nt360.
_DATE_ORDER = (
    "COALESCE(c.date_commande || ' 00:00:00.000000', s.date_order, "
    "CASE WHEN c.year_po IS NULL THEN NULL "
    "WHEN substr(c.date_ecriture, 1, 4) = CAST(c.year_po AS TEXT) "
    "THEN substr(c.date_ecriture, 1, 10) || ' 00:00:00.000000' "
    "ELSE c.year_po || '-12-31 00:00:00.000000' END)"
)

# Compatibilité : mêmes colonnes que `sale_orders`, contenu nt360. Les lecteurs
# basculent en changeant seulement le nom de table ; l'écriture (synchro Odoo,
# webhooks, scripts) reste sur la vraie table `sale_orders`.
#   amount / amount_untaxed = cas nt360, HT (sale_orders.amount était TTC)
#   client_name / salesperson_name = libellés nt360 (normalisés)
#   date_order = date_commande nt360 (identique à Odoo au jour près), repli Odoo
#   state = 'sale' : nt360 ne publie que des commandes valides
# Les colonnes de marge restent celles d'Odoo, seule source qui les porte.
#
# REPLI ODOO : tant que nt360 n'a jamais été synchronisé (clé absente, premier
# démarrage avant la première synchro), la vue rend `sale_orders` tel quel.
# Sans ce repli, chaque écran afficherait un CA nul dans cet intervalle. La
# bascule est tout-ou-rien, jamais un mélange des deux sources.
_NT360_COMMANDES_ACTIF = "EXISTS (SELECT 1 FROM nt360_commandes)"
_NT360_FACTURES_ACTIF = "EXISTS (SELECT 1 FROM nt360_factures)"

_V_SALE_ORDERS = f"""
CREATE VIEW v_sale_orders AS
SELECT
    COALESCE(c.order_id, 'nt360:' || c.fp) AS order_id,
    s.odoo_id,
    COALESCE(c.client_id, '') AS client_id,
    c.client_name,
    c.fp AS name,
    c.montant_ht AS amount,
    c.montant_ht AS amount_untaxed,
    'XOF' AS currency,
    {_DATE_ORDER} AS date_order,
    'sale' AS state,
    c.salesperson_name,
    c.dossier_id,
    COALESCE(s.order_lines, '[]') AS order_lines,
    COALESCE(s.invoice_ids, '[]') AS invoice_ids,
    COALESCE(s.purchase_total, 0.0) AS purchase_total,
    COALESCE(s.approach_costs, 0.0) AS approach_costs,
    COALESCE(s.provision, 0.0) AS provision,
    COALESCE(s.margin_amount, 0.0) AS margin_amount,
    COALESCE(s.margin_pct, 0.0) AS margin_pct,
    c.synced_at,
    c.entite,
    c.entite_source
FROM v_commandes c
LEFT JOIN sale_orders s ON s.order_id = c.order_id
UNION ALL
SELECT
    order_id, odoo_id, client_id, client_name, name, amount, amount_untaxed, currency,
    date_order, state, salesperson_name, dossier_id, order_lines, invoice_ids,
    purchase_total, approach_costs, provision, margin_amount, margin_pct, synced_at, '', ''
FROM sale_orders
WHERE NOT {_NT360_COMMANDES_ACTIF}
"""

_V_LIGNES_COMMANDE = f"""
CREATE VIEW v_lignes_commande AS
SELECT
    c.fp,
    l.line_id,
    'odoo' AS origine,
    c.order_id,
    COALESCE(c.client_id, '') AS client_id,
    c.client_name,
    c.salesperson_name,
    c.bu,
    c.year_po,
    c.date_commande,
    {_DATE_ORDER} AS date_order,
    'sale' AS state,
    l.product_code,
    l.product_name,
    l.product_category,
    l.vendor,
    l.qty,
    l.subtotal_xof AS montant_ht_odoo,
    l.subtotal_xof * c.coefficient AS montant_ht,
    c.coefficient,
    l.purchase_price_xof,
    c.entite,
    c.entite_source
FROM v_commandes c
JOIN sale_order_lines l ON l.order_id = c.order_id AND l.display_type IS NULL
LEFT JOIN sale_orders s ON s.order_id = c.order_id
UNION ALL
SELECT
    c.fp,
    'ajustement:' || c.fp,
    'ajustement',
    COALESCE(c.order_id, 'nt360:' || c.fp),
    COALESCE(c.client_id, ''),
    c.client_name,
    c.salesperson_name,
    c.bu,
    c.year_po,
    c.date_commande,
    {_DATE_ORDER},
    'sale',
    '',
    'non détaillé',
    '',
    '',
    NULL,
    NULL,
    c.ajustement,
    NULL,
    0.0,
    c.entite,
    c.entite_source
FROM v_commandes c
LEFT JOIN sale_orders s ON s.order_id = c.order_id
WHERE ABS(c.ajustement) > 0.5
UNION ALL
-- Repli Odoo (nt360 jamais synchronisé) : lignes brutes des commandes valides.
SELECT
    s.name, l.line_id, 'odoo', s.order_id, s.client_id, s.client_name, s.salesperson_name,
    '', CAST(strftime('%Y', s.date_order) AS INTEGER), date(s.date_order), s.date_order, s.state,
    l.product_code, l.product_name, l.product_category, l.vendor, l.qty,
    l.subtotal_xof, l.subtotal_xof, 1.0, l.purchase_price_xof, '', ''
FROM sale_order_lines l
JOIN sale_orders s ON s.order_id = l.order_id
WHERE l.display_type IS NULL AND s.state IN ('sale', 'done')
  AND NOT {_NT360_COMMANDES_ACTIF}
"""

# Factures : nt360 fait foi pour le FACTURÉ (HT, avoirs déduits — 151 avoirs que
# le miroir Odoo ne porte pas). Odoo reste joint pour ce que nt360 ne date pas :
# date de paiement, reste dû TTC et statut de recouvrement. Les créances
# (impayés, relances, DSO, trésorerie) continuent donc de lire `invoices` :
# l'argent dû par un client est TTC, et nt360 ne date aucun règlement.
#   amount     = HT nt360 (TTC Odoo en repli, cf. base_montant)
#   rapprochement : conforme / statut_divergent (payée d'un côté seulement) /
#                   annulee_odoo / absente_odoo
_V_FACTURES = f"""
CREATE VIEW v_factures AS
SELECT
    f.numero,
    f.fp,
    f.dc,
    f.client AS client_name,
    COALESCE(NULLIF(i.client_id, ''), c.client_id, '') AS client_id,
    f.bu,
    f.filiale,
    f.date_facture || ' 00:00:00.000000' AS invoice_date,
    f.due_date,
    f.amount_ht AS amount,
    'HT' AS base_montant,
    f.regle AS regle_ht,
    f.reste_a_payer AS reste_a_payer_ht,
    f.paid,
    f.payment_status,
    f.currency AS devise_origine,
    'nt360' AS source,
    i.invoice_id,
    i.amount AS montant_ttc_odoo,
    i.amount_residual AS reste_ttc_odoo,
    i.status AS statut_odoo,
    i.payment_date,
    CASE
        WHEN i.invoice_id IS NULL THEN 'absente_odoo'
        WHEN i.status = 'cancelled' THEN 'annulee_odoo'
        WHEN f.paid AND i.status != 'paid' THEN 'statut_divergent'
        WHEN NOT f.paid AND i.status = 'paid' THEN 'statut_divergent'
        ELSE 'conforme'
    END AS rapprochement,
    -- Pays : filiale nt360, puis commande de même FP.
    COALESCE(NULLIF(f.filiale, ''), e.entite, '') AS entite,
    CASE WHEN NULLIF(f.filiale, '') IS NOT NULL THEN 'filiale'
         WHEN e.entite IS NOT NULL THEN 'commande_fp' ELSE '' END AS entite_source
FROM nt360_factures f
LEFT JOIN invoices i ON i.invoice_name = f.numero
LEFT JOIN v_commandes c ON c.fp = f.fp
LEFT JOIN v_entite_fp e ON e.fp = f.fp
UNION ALL
SELECT
    i.invoice_name, NULL, NULL, cl.name, i.client_id, NULL, NULL,
    i.invoice_date, i.due_date, i.amount, 'TTC',
    i.amount - i.amount_residual, i.amount_residual, i.status = 'paid', i.status, i.currency,
    'odoo', i.invoice_id, i.amount, i.amount_residual, i.status, i.payment_date, 'conforme', '', ''
FROM invoices i
LEFT JOIN clients cl ON cl.client_id = i.client_id
WHERE i.status != 'cancelled' AND NOT {_NT360_FACTURES_ACTIF}
"""

# Achats : BC fournisseurs nt360 au format de `purchase_orders`. Ne contient que
# les BC ENGAGÉS (émis, livrés, soldés) — ce que `purchase_orders` (état
# 'purchase') a toujours représenté pour ses lecteurs. Les BC « à émettre »
# (439, issus des fiches, pas encore dans Odoo) et annulés restent lisibles dans
# nt360_bc. Jointure Odoo : bcNumber = purchase_orders.name (100 %).
#   amount      = amountXof nt360, HT (Odoo amount_total est TTC sur ~1/3 des BC)
#   client_name / client_id = fournisseur ODOO quand le BC y est : nt360 n'en
#                 donne qu'un code (MICROSFT, MULTISOL), et la fiche fournisseur
#                 (crédit, délai de paiement) se joint par ce nom et cet id
#   dossier_id  = N° DC nt360, sinon celui d'Odoo (~45 % des BC en portent un ;
#                 99 % de ceux-là existent bien dans `dossiers`)
_V_PURCHASE_ORDERS = """
CREATE VIEW v_purchase_orders AS
SELECT
    COALESCE(p.order_id, 'nt360:' || b.id) AS order_id,
    p.odoo_id,
    COALESCE(p.client_id, '') AS client_id,
    COALESCE(NULLIF(TRIM(p.client_name), ''), b.supplier) AS client_name,
    COALESCE(NULLIF(b.bc_number, ''), b.id) AS name,
    b.amount_xof AS amount,
    'XOF' AS currency,
    COALESCE(b.date_in || ' 00:00:00.000000', p.date_order) AS date_order,
    'purchase' AS state,
    b.synced_at,
    COALESCE(NULLIF(b.dc, ''), p.dossier_id) AS dossier_id,
    b.status AS statut_nt360,
    b.fp,
    b.expense_type,
    b.eta_contrat,
    b.eta_reel,
    -- Deux pays, deux questions : `entite` = pays de l'AFFAIRE servie (commande
    -- de même FP) — « que coûtent les affaires du Burkina ? » ; `entite_achat` =
    -- filiale qui ACHÈTE — « qu'achète l'entité Burkina ? ». 180 BC émis par la
    -- CI servent des affaires BF : les deux ne se confondent pas.
    COALESCE(e.entite, '') AS entite,
    CASE WHEN e.entite IS NOT NULL THEN 'commande_fp' ELSE '' END AS entite_source,
    COALESCE(NULLIF(b.filiale, ''), '') AS entite_achat
FROM nt360_bc b
LEFT JOIN purchase_orders p ON p.name = b.bc_number AND b.bc_number != ''
LEFT JOIN v_entite_fp e ON e.fp = b.fp AND b.fp != ''
WHERE b.status NOT IN ('a_emettre', 'annule')
UNION ALL
SELECT
    order_id, odoo_id, client_id, client_name, name, amount, currency, date_order, state,
    synced_at, dossier_id, NULL, NULL, NULL, NULL, NULL, '', '', ''
FROM purchase_orders
WHERE NOT EXISTS (SELECT 1 FROM nt360_bc)
"""

# Opportunités : nt360 fait foi pour l'UNIVERS (quelles affaires existent), leur
# étape, montant, probabilité, commercial, client et date de clôture. nt360 a
# écarté 1 230 opportunités Odoo (perdues, suspendues, annulées…) : elles sortent
# de toutes les lectures. Odoo complète ce que nt360 ne porte pas, par l'id
# Odoo (`odoo_crm.lead:12900` = opp_12900) :
#   name        = titre Odoo ; à défaut l'affaire de la commande nt360 (même FP)
#   created_at / write_date / date_closed / order_ids / offer_family = Odoo
#                 (NULL pour les saisies nt360 sans opportunité Odoo)
#   client_id   = Odoo, sinon celui de la commande (même FP)
# Repli Odoo tant que nt360 n'a jamais été synchronisé.
_EQUIPE_OPP = sql_equipe_vers_pays("o.equipe")

_V_OPPORTUNITIES = f"""
CREATE VIEW v_opportunities AS
SELECT
    COALESCE(n.opp_id, 'nt360:' || n.id) AS opp_id,
    o.odoo_id,
    COALESCE(NULLIF(o.client_id, ''), c.client_id, '') AS client_id,
    n.client AS client_name,
    COALESCE(NULLIF(o.name, ''), NULLIF(c.affaire, ''), n.client) AS name,
    n.stage_label AS stage,
    n.amount AS expected_revenue,
    n.probability,
    n.am AS salesperson_name,
    n.closing_date || ' 00:00:00.000000' AS deadline,
    o.created_at,
    n.synced_at,
    o.write_date,
    o.date_closed,
    1 AS active,
    COALESCE(o.order_ids, '[]') AS order_ids,
    o.offer_family,
    n.fp,
    n.bu,
    n.weighted,
    n.source,
    n.stage AS stage_num,
    -- Pays : commande de même FP (affaire gagnée) → équipe Odoo désignant un
    -- pays → commercial mono-pays (24 mois) → non rattaché. Une opportunité
    -- ouverte a un N° FP mais pas encore de commande : d'où les replis.
    COALESCE(e.entite, {_EQUIPE_OPP}, com.entite, '') AS entite,
    CASE WHEN e.entite IS NOT NULL THEN 'commande_fp'
         WHEN {_EQUIPE_OPP} IS NOT NULL THEN 'equipe'
         WHEN com.entite IS NOT NULL THEN 'commercial'
         ELSE '' END AS entite_source
FROM nt360_opportunites n
LEFT JOIN opportunities o ON o.opp_id = n.opp_id
LEFT JOIN v_commandes c ON c.fp = n.fp AND n.fp != ''
LEFT JOIN v_entite_fp e ON e.fp = n.fp AND n.fp != ''
LEFT JOIN v_entite_commercial com ON com.am = UPPER(TRIM(n.am))
UNION ALL
SELECT
    opp_id, odoo_id, client_id, client_name, name, stage, expected_revenue, probability,
    salesperson_name, deadline, created_at, synced_at, write_date, date_closed, 1,
    order_ids, offer_family, NULL, NULL, NULL, 'odoo', NULL, '', ''
FROM opportunities
WHERE NOT EXISTS (SELECT 1 FROM nt360_opportunites)
"""

# Créances : `invoices` (Odoo, TTC — l'argent dû) avec son pays. Mêmes colonnes
# que la table : ses lecteurs basculent en changeant seulement le nom de table.
# Pays : facture nt360 de même numéro (filiale, puis commande de même FP) →
# équipe Odoo désignant un pays → non rattaché.
_EQUIPE_INV = sql_equipe_vers_pays("i.equipe")

_V_CREANCES = f"""
CREATE VIEW v_creances AS
SELECT
    i.*,
    COALESCE(NULLIF(f.filiale, ''), e.entite, {_EQUIPE_INV}, '') AS entite,
    CASE WHEN COALESCE(NULLIF(f.filiale, ''), e.entite) IS NOT NULL THEN 'facture'
         WHEN {_EQUIPE_INV} IS NOT NULL THEN 'equipe'
         ELSE '' END AS entite_source
FROM invoices i
LEFT JOIN nt360_factures f ON f.numero = i.invoice_name
LEFT JOIN v_entite_fp e ON e.fp = f.fp AND f.fp != ''
"""

# Dossiers : `dossiers` (Odoo) avec son pays, par le N° DC des factures et BC nt360.
_V_DOSSIERS = """
CREATE VIEW v_dossiers AS
SELECT
    d.*,
    COALESCE(x.entite, '') AS entite,
    CASE WHEN x.entite IS NOT NULL THEN 'dossier_dc' ELSE '' END AS entite_source
FROM dossiers d
LEFT JOIN v_entite_dc x ON x.dc = d.dossier_ref
"""


# Montants TTC Odoo, avec pays. Le DAF rapproche le CA et les achats d'argent qui
# circule réellement (encours client, décaissements), donc en TTC : ces deux vues
# portent les tables brutes `sale_orders` / `purchase_orders` à l'identique, plus
# le pays — sans elles, un DSO par pays diviserait un encours du pays par un CA
# TTC du groupe.
_EQUIPE_SO = sql_equipe_vers_pays("s.equipe")

_V_SALE_ORDERS_ODOO = f"""
CREATE VIEW v_sale_orders_odoo AS
SELECT
    s.*,
    COALESCE(e.entite, {_EQUIPE_SO}, '') AS entite,
    CASE WHEN e.entite IS NOT NULL THEN 'commande_fp'
         WHEN {_EQUIPE_SO} IS NOT NULL THEN 'equipe' ELSE '' END AS entite_source
FROM sale_orders s
LEFT JOIN v_entite_fp e ON e.fp = s.name
"""

_V_ACHATS_ODOO = """
CREATE VIEW v_achats_odoo AS
SELECT
    p.*,
    COALESCE(e.entite, '') AS entite,
    CASE WHEN e.entite IS NOT NULL THEN 'commande_fp' ELSE '' END AS entite_source
FROM purchase_orders p
LEFT JOIN nt360_bc b ON b.bc_number = p.name AND b.bc_number != ''
LEFT JOIN v_entite_fp e ON e.fp = b.fp AND b.fp != ''
"""


def _vue_par_fp(nom: str, table: str, colonne_fp: str) -> str:
    """Table nt360 portant un N° FP, augmentée du pays de sa commande."""
    return f"""
CREATE VIEW {nom} AS
SELECT
    t.*,
    COALESCE(e.entite, '') AS entite,
    CASE WHEN e.entite IS NOT NULL THEN 'commande_fp' ELSE '' END AS entite_source
FROM {table} t
LEFT JOIN v_entite_fp e ON e.fp = t.{colonne_fp} AND t.{colonne_fp} != ''
"""


# Consultations : pas de N° FP, mais une filiale nt360 sur 100 % d'entre elles.
_V_CONSULTATIONS = """
CREATE VIEW v_consultations AS
SELECT
    t.*,
    COALESCE(NULLIF(t.filiale, ''), '') AS entite,
    CASE WHEN NULLIF(t.filiale, '') IS NOT NULL THEN 'filiale' ELSE '' END AS entite_source
FROM nt360_consultations t
"""

# Ordre de création : pivots d'abord, puis v_commandes que les autres lisent.
VUES: list[tuple[str, str]] = [
    ("v_entite_fp", _V_ENTITE_FP),
    ("v_entite_commercial", _V_ENTITE_COMMERCIAL),
    ("v_entite_dc", _V_ENTITE_DC),
    ("v_commandes", _V_COMMANDES),
    ("v_sale_orders", _V_SALE_ORDERS),
    ("v_lignes_commande", _V_LIGNES_COMMANDE),
    ("v_factures", _V_FACTURES),
    ("v_purchase_orders", _V_PURCHASE_ORDERS),
    ("v_opportunities", _V_OPPORTUNITIES),
    ("v_creances", _V_CREANCES),
    ("v_dossiers", _V_DOSSIERS),
    ("v_jalons", _vue_par_fp("v_jalons", "nt360_jalons", "fp")),
    ("v_demandes_facturation", _vue_par_fp("v_demandes_facturation", "nt360_demandes_facturation", "fp")),
    ("v_fiches", _vue_par_fp("v_fiches", "nt360_fiches", "numero_fp")),
    ("v_consultations", _V_CONSULTATIONS),
    ("v_sale_orders_odoo", _V_SALE_ORDERS_ODOO),
    ("v_achats_odoo", _V_ACHATS_ODOO),
]


# ── Modèle ORM en lecture seule sur v_sale_orders ───────────────────────────
# Métadonnées SÉPARÉES de Base : `create_all` ne doit jamais créer de table
# portant le nom d'une vue (la vue ne pourrait plus être créée ensuite).
class _VueBase(DeclarativeBase):
    pass


class VSaleOrderModel(_VueBase):
    """Lecture seule — commandes nt360 au format de SaleOrderModel. Ne jamais
    y écrire : c'est une vue (cf. _V_SALE_ORDERS)."""
    __tablename__ = "v_sale_orders"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_id: Mapped[str] = mapped_column(String)
    client_name: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    amount_untaxed: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10))
    date_order: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(50))
    salesperson_name: Mapped[str] = mapped_column(String(255))
    dossier_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_lines: Mapped[list] = mapped_column(JSON)
    invoice_ids: Mapped[list] = mapped_column(JSON)
    purchase_total: Mapped[float] = mapped_column(Float)
    approach_costs: Mapped[float] = mapped_column(Float)
    provision: Mapped[float] = mapped_column(Float)
    margin_amount: Mapped[float] = mapped_column(Float)
    margin_pct: Mapped[float] = mapped_column(Float)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    entite: Mapped[str] = mapped_column(String(10))   # CI | BF | GN ("" en repli Odoo)


class VOpportunityModel(_VueBase):
    """Lecture seule — opportunités nt360 au format d'OpportunityModel (cf.
    _V_OPPORTUNITIES). Ne jamais y écrire."""
    __tablename__ = "v_opportunities"

    opp_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String, nullable=True)
    client_name: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(500))
    stage: Mapped[str] = mapped_column(String(100))
    expected_revenue: Mapped[float] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float)
    salesperson_name: Mapped[str] = mapped_column(String(255))
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    write_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_closed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    order_ids: Mapped[list] = mapped_column(JSON)
    offer_family: Mapped[str | None] = mapped_column(String(30), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VPurchaseOrderModel(_VueBase):
    """Lecture seule — BC engagés nt360 au format de PurchaseOrderModel (cf.
    _V_PURCHASE_ORDERS). Ne jamais y écrire."""
    __tablename__ = "v_purchase_orders"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_id: Mapped[str] = mapped_column(String)
    client_name: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10))
    date_order: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(50))
    dossier_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def create_views(sync_conn) -> None:
    """Recrée les vues (idempotent). À appeler après création/migration des tables."""
    for nom, _ in reversed(VUES):
        sync_conn.exec_driver_sql(f"DROP VIEW IF EXISTS {nom}")
    for _, ddl in VUES:
        sync_conn.exec_driver_sql(ddl)


def _modele_vue(nom_classe: str, vue: str, modele) -> type:
    """Modèle ORM en lecture seule sur une vue « table + pays » : mêmes colonnes
    que `modele` (recopiées, donc jamais en retard d'une migration), plus
    `entite` et `entite_source`. Les lecteurs ORM basculent en changeant de classe."""
    attrs: dict = {"__tablename__": vue, "__doc__": f"Lecture seule — {vue} (cf. db/views.py)."}
    for col in modele.__table__.columns:
        attrs[col.name] = mapped_column(col.type, primary_key=col.primary_key, nullable=not col.primary_key)
    attrs["entite"] = mapped_column(String(10))
    attrs["entite_source"] = mapped_column(String(20))
    return type(nom_classe, (_VueBase,), attrs)


def _modeles_rattachement():
    from db.models import DossierModel, InvoiceModel
    return (
        _modele_vue("VCreanceModel", "v_creances", InvoiceModel),
        _modele_vue("VDossierModel", "v_dossiers", DossierModel),
    )


VCreanceModel, VDossierModel = _modeles_rattachement()
