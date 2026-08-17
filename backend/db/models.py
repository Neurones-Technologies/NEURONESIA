from datetime import date, datetime
from typing import Optional

from sqlalchemy import String, Float, Boolean, DateTime, Date, JSON, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


class GEDEntryModel(Base):
    __tablename__ = "ged_entries"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    file_path: Mapped[str] = mapped_column(String, unique=True, index=True)
    hash_sha256: Mapped[str] = mapped_column(String(64))
    doc_type: Mapped[str] = mapped_column(String(50))
    last_indexed: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    vector_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ClientModel(Base):
    __tablename__ = "clients"

    client_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    solvency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContractModel(Base):
    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String(500))
    value: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="XOF")
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvoiceModel(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="XOF")
    due_date: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    invoice_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invoice_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    amount_residual: Mapped[float] = mapped_column(Float, default=0.0)  # montant restant à payer
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectModel(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    engineers: Mapped[list] = mapped_column(JSON, default=list)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SaleOrderModel(Base):
    __tablename__ = "sale_orders"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    client_name: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)   # ex: FP/2026/12977
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="XOF")
    date_order: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(50), default="sale")  # draft/sale/done/cancel
    salesperson_name: Mapped[str] = mapped_column(String(255), default="")
    dossier_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_lines: Mapped[list] = mapped_column(JSON, default=list)
    invoice_ids: Mapped[list] = mapped_column(JSON, default=list)  # IDs Odoo des account.move liées (sale.order.invoice_ids)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseOrderModel(Base):
    __tablename__ = "purchase_orders"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)   # vendor partner_id
    client_name: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)   # ex: PO/2026/00123
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="XOF")
    date_order: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(50), default="purchase")
    # Lien vers le dossier commercial (neurones.dossier.manager, cf. DossierModel) — même
    # champ que SaleOrderModel.dossier_id, disponible côté Odoo sur purchase.order aussi.
    # Permet de relier une commande fournisseur à la marge RÉELLE de la mission qu'elle a
    # servie (cf. get_supplier_intelligence dans local_crm_adapter.py).
    dossier_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupplierModel(Base):
    """Miroir de res.partner (côté fournisseur, supplier_rank > 0) — distinct de
    ClientModel qui ne couvre QUE les clients (customer_rank > 0, cf. get_all_clients).
    Porte les infos indisponibles ailleurs : plafond de crédit et délai de paiement
    négocié, nécessaires pour juger objectivement de notre exposition à ce fournisseur."""
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String, primary_key=True)  # str(partner_id)
    odoo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    credit_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    use_partner_credit_limit: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_term_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nombre de jours de la tranche la PLUS ÉLOIGNÉE du terme négocié (ex: "30% à 30j,
    # 70% à 60j" → 60) : le pire cas de règlement complet, comparable à un retard réel.
    payment_term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_rank: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupplierInvoiceModel(Base):
    """Factures FOURNISSEURS (account.move, move_type=in_invoice) — jamais synchronisées
    avant ce soir (seules les factures clients out_invoice l'étaient, cf. InvoiceModel).
    Table SÉPARÉE délibérément : de nombreuses requêtes existantes lisent `invoices` sans
    filtrer par move_type (cf. get_unpaid_invoices, dashboards trésorerie) — y mélanger des
    factures fournisseurs casserait ces calculs en silence. Payables et receivables sont
    deux domaines distincts, gardés dans deux tables distinctes."""
    __tablename__ = "supplier_invoices"

    invoice_id: Mapped[str] = mapped_column(String, primary_key=True)
    odoo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    supplier_id: Mapped[str] = mapped_column(String, index=True)  # vendor partner_id
    supplier_name: Mapped[str] = mapped_column(String(255), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    amount_residual: Mapped[float] = mapped_column(Float, default=0.0)  # reste dû
    currency: Mapped[str] = mapped_column(String(10), default="XOF")
    invoice_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    payment_state: Mapped[str] = mapped_column(String(50), default="not_paid")
    # Date RÉELLE de règlement (account.payment via invoice_payments_widget, même
    # mécanisme que InvoiceModel.payment_date côté clients) — permet de comparer le délai
    # de paiement RÉEL au délai négocié (SupplierModel.payment_term_days), pas une
    # heuristique sur les factures encore ouvertes.
    payment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="user")   # "admin" | "user" | "viewer"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModulePermissionModel(Base):
    """Surcharge d'une cellule de la matrice module × rôle (écran Administration).

    Table vide = matrice par défaut de config/permissions.py. Chaque ligne
    remplace UNE cellule (view, role) — les défauts restent la référence pour
    toutes les cellules non surchargées.
    """
    __tablename__ = "module_permissions"
    __table_args__ = (Index("ix_module_perm_view_role", "view", "role", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    view: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(50))
    allowed: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationModel(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conv_session_user_time", "session_id", "user_id", "created_at"),
        # Liste de l'historique du Copilote : toujours filtrée (user, profil) et
        # triée par date — cet index couvre exactement cette lecture.
        Index("ix_conv_user_profile_time", "user_id", "profile", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Profil cockpit d'où part la conversation ("dg" | "dc" | "do" | "df" | "am").
    # L'historique est cloisonné par profil : un DG ne retrouve pas dans son
    # Copilote les conversations qu'il a menées côté profil commercial.
    profile: Mapped[str] = mapped_column(String(20), default="")
    role: Mapped[str] = mapped_column(String(20))        # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TokenUsageModel(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    use_case: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_fcfa: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VeilleSourceModel(Base):
    __tablename__ = "veille_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(500))
    feed_type: Mapped[str] = mapped_column(String(50), default="rss")  # "rss" | "html"
    keywords: Mapped[str] = mapped_column(String(1000), default="")   # mots-clés séparés par virgules
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_scan: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class VeilleEntryModel(Base):
    __tablename__ = "veille_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("veille_sources.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(String(2000), default="")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(50), default="new")   # "new" | "read" | "archived" | "in_presales"
    estimated_budget: Mapped[str] = mapped_column(String(200), default="")
    deadline: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(100), default="CI")
    relevance_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100

    # ── Analyse IA S2I (agent Watch-Tracker) : signal → risque → offre ──────────
    # Rempli par modules/uc_veille/classifier.py au moment du scan. ai_analyzed
    # distingue une entrée traitée par Claude d'une entrée brute (repli front).
    ai_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    signal_label: Mapped[str] = mapped_column(String(255), default="")
    risque: Mapped[str] = mapped_column(String(500), default="")
    offre: Mapped[str] = mapped_column(String(500), default="")
    offre_short: Mapped[str] = mapped_column(String(100), default="")
    priority: Mapped[str] = mapped_column(String(20), default="")   # CRITIQUE | ELEVEE | MOYENNE | ""
    criticite: Mapped[int] = mapped_column(Integer, default=0)      # 0-100 (score IA argumenté)
    organisation: Mapped[str] = mapped_column(String(255), default="")
    justification: Mapped[str] = mapped_column(String(1000), default="")
    origin: Mapped[str] = mapped_column(String(20), default="source")  # "source" | "web"
    # Lecture marché du signal (lue par uc_commercial.fetch_veille) : `axe` est
    # l'axe de marché rattaché au signal — son taux de remplissage EST le taux de
    # couverture servi au DC, d'où la sentinelle "" plutôt que NULL. `so_what` et
    # `action_suggeree` portent l'interprétation et la suite à donner.
    axe: Mapped[str] = mapped_column(String(100), default="")
    so_what: Mapped[str] = mapped_column(String(1000), default="")
    action_suggeree: Mapped[str] = mapped_column(String(1000), default="")
    # Débriefing pré-généré au scan (Claude lit la page réelle) : affiché tel quel
    # au clic, sans nouvelle génération ni lecture web. Vide = pas encore généré.
    debrief: Mapped[str] = mapped_column(Text, default="")


class VeilleConfigModel(Base):
    """Configuration globale de l'agent Watch-Tracker (ligne unique, id=1).

    Pilote « ce sur quoi l'agent se base » : thèmes prioritaires injectés dans le
    prompt Claude, et bascule d'exploration web.
    """
    __tablename__ = "veille_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # singleton : toujours 1
    themes: Mapped[str] = mapped_column(String(2000), default="")
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OpportunityModel(Base):
    __tablename__ = "opportunities"

    opp_id: Mapped[str] = mapped_column(String, primary_key=True)   # "opp_{odoo_id}"
    odoo_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    client_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    client_name: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(500))
    stage: Mapped[str] = mapped_column(String(100), default="")
    expected_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    probability: Mapped[float] = mapped_column(Float, default=0.0)   # 0–100
    salesperson_name: Mapped[str] = mapped_column(String(255), default="")
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Datation du CYCLE de vente (crm.lead.date_closed / write_date) : `date_closed`
    # n'est renseignée que sur les opportunités effectivement closes — NULL sur tout
    # ce qui est encore au pipe, d'où le nullable. C'est le couple created_at →
    # date_closed qui donne la durée de cycle mesurée (cf. uc_commercial/statique.py).
    date_closed: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    write_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    order_ids: Mapped[list] = mapped_column(JSON, default=list)  # IDs Odoo des sale.order générés par cette opportunité
    # Famille d'offre DÉDUITE du libellé (modules.uc_offermix.taxonomy) : logiciel /
    # reseau / equipement / services, NULL si le libellé ne permet pas de trancher.
    # Champ dérivé et recalculable — stocké pour la performance et pour que les
    # snapshots quotidiens rendent l'historique ventilable. Odoo ne porte aucune
    # catégorie sur crm.lead, et la voie « lignes de commande » est inexploitable
    # (40 opportunités sur 6 675 ont un order_ids non vide).
    offer_family: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QuarantineModel(Base):
    """Fichiers rejetés par le QualityValidator — en attente de correction manuelle."""
    __tablename__ = "quarantine"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String, unique=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(1000))
    quarantined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    text_length: Mapped[int] = mapped_column(Integer, default=0)


class DossierModel(Base):
    """Miroir de neurones.dossier.manager — dossiers commerciaux avec marges."""
    __tablename__ = "dossiers"

    dossier_ref: Mapped[str] = mapped_column(String(50), primary_key=True)   # ex: DC/2026/0154
    odoo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(255), index=True, default="")
    project_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    salesperson: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="draft")   # draft/confirmed/done/cancel
    date_creation: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    date_end_project: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Chiffre d'affaires
    ca_provisoire: Mapped[float] = mapped_column(Float, default=0.0)
    ca_definitif: Mapped[float] = mapped_column(Float, default=0.0)
    # Dépenses
    depense_provisoire: Mapped[float] = mapped_column(Float, default=0.0)
    depense_definitive: Mapped[float] = mapped_column(Float, default=0.0)
    # Marges (valeur)
    marge_previsionnelle: Mapped[float] = mapped_column(Float, default=0.0)
    marge_provisoire: Mapped[float] = mapped_column(Float, default=0.0)
    marge_definitive: Mapped[float] = mapped_column(Float, default=0.0)
    # Marges (%)
    perc_marge_previsionnelle: Mapped[float] = mapped_column(Float, default=0.0)
    perc_marge_provisoire: Mapped[float] = mapped_column(Float, default=0.0)
    perc_marge_definitive: Mapped[float] = mapped_column(Float, default=0.0)
    # Encaissements / fournisseurs
    montant_recu: Mapped[float] = mapped_column(Float, default=0.0)
    reste_a_encaisser: Mapped[float] = mapped_column(Float, default=0.0)
    backlog: Mapped[float] = mapped_column(Float, default=0.0)
    fournisseurs_payes: Mapped[float] = mapped_column(Float, default=0.0)
    fournisseurs_restant: Mapped[float] = mapped_column(Float, default=0.0)
    # Compteurs
    nb_bdc: Mapped[int] = mapped_column(Integer, default=0)
    nb_factures_client: Mapped[int] = mapped_column(Integer, default=0)
    nb_factures_fournisseur: Mapped[int] = mapped_column(Integer, default=0)
    nb_achats: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════════════════════
# COUCHE STRUCTURÉE (kb_*) — faits typés extraits des documents GED (Phase 1).
# Préfixe `kb_` pour ne PAS entrer en collision avec les tables miroir Odoo
# `clients` / `projects`. Alimentées par le StructuredExtractor + SQLiteKBAdapter.
# ════════════════════════════════════════════════════════════════════════════


class _KBFactCommon:
    """Colonnes techniques communes à toute table de faits (traçabilité + audit).

    `doc_id` n'est PAS ici : les tables de tête l'utilisent en clé primaire,
    les tables enfants en colonne indexée + FK logique.
    """
    doc_type: Mapped[str] = mapped_column(String(50), default="")
    fichier_source: Mapped[str] = mapped_column(String, default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hash_sha256: Mapped[str] = mapped_column(String(64), default="")
    date_ingestion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    score_confiance: Mapped[float] = mapped_column(Float, default=0.0)
    revue_humaine: Mapped[bool] = mapped_column(Boolean, default=False)


# ── Entités canoniques (pivots) — créées en P1, peuplées en P2 ───────────────

class KBClientModel(Base):
    __tablename__ = "kb_clients"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(255), index=True)
    secteur: Mapped[str | None] = mapped_column(String(150), nullable=True)
    pays: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KBPersonneModel(Base):
    __tablename__ = "kb_personnes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    nom_complet: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KBProjetModel(Base):
    __tablename__ = "kb_projets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    intitule: Mapped[str] = mapped_column(String(500), index=True)
    client_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_clients.id"), nullable=True)
    secteur: Mapped[str | None] = mapped_column(String(150), nullable=True)
    montant_valeur: Mapped[float | None] = mapped_column(Float, nullable=True)
    montant_devise: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_debut: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ── CV ───────────────────────────────────────────────────────────────────────

class KBCvModel(Base, _KBFactCommon):
    __tablename__ = "kb_cv"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    nom_complet: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    titre_poste: Mapped[str | None] = mapped_column(String(255), nullable=True)
    annees_experience: Mapped[float | None] = mapped_column(Float, nullable=True)
    localisation: Mapped[str | None] = mapped_column(String(150), nullable=True)
    personne_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_personnes.id"), nullable=True)
    langues: Mapped[list] = mapped_column(JSON, default=list)
    competences: Mapped[list] = mapped_column(JSON, default=list)
    formations: Mapped[list] = mapped_column(JSON, default=list)
    secteurs_expertise: Mapped[list] = mapped_column(JSON, default=list)


class KBCvExperienceModel(Base):
    __tablename__ = "kb_cv_experiences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("kb_cv.doc_id"), index=True)
    intitule_projet: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secteur: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    date_debut: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    en_cours: Mapped[bool] = mapped_column(Boolean, default=False)
    description_courte: Mapped[str | None] = mapped_column(Text, nullable=True)
    projet_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_projets.id"), nullable=True)


class KBCvCertificationModel(Base):
    __tablename__ = "kb_cv_certifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("kb_cv.doc_id"), index=True)
    intitule: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    organisme: Mapped[str | None] = mapped_column(String(255), nullable=True)
    annee: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ── Appel d'offres ───────────────────────────────────────────────────────────

class KBAoModel(Base, _KBFactCommon):
    __tablename__ = "kb_ao"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    intitule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    maitre_ouvrage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_publication: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_limite_remise: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    budget_valeur: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_devise: Mapped[str | None] = mapped_column(String(10), nullable=True)
    type_marche: Mapped[str | None] = mapped_column(String(150), nullable=True)
    duree_execution: Mapped[str | None] = mapped_column(String(150), nullable=True)
    client_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_clients.id"), nullable=True)
    projet_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_projets.id"), nullable=True)
    lots: Mapped[list] = mapped_column(JSON, default=list)
    certifications_exigees: Mapped[list] = mapped_column(JSON, default=list)
    criteres_evaluation: Mapped[list] = mapped_column(JSON, default=list)


class KBAoExigenceModel(Base):
    __tablename__ = "kb_ao_exigences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("kb_ao.doc_id"), index=True)
    categorie: Mapped[str | None] = mapped_column(String(50), nullable=True)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    obligatoire: Mapped[bool] = mapped_column(Boolean, default=True)


class KBAoReferenceDemandeeModel(Base):
    __tablename__ = "kb_ao_references_demandees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("kb_ao.doc_id"), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    nombre_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    montant_min_valeur: Mapped[float | None] = mapped_column(Float, nullable=True)
    montant_min_devise: Mapped[str | None] = mapped_column(String(10), nullable=True)
    periode: Mapped[str | None] = mapped_column(String(150), nullable=True)


# ── Compte rendu ─────────────────────────────────────────────────────────────

class KBCompteRenduModel(Base, _KBFactCommon):
    __tablename__ = "kb_compte_rendu"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    date_reunion: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    objet: Mapped[str | None] = mapped_column(String(500), nullable=True)
    projet_associe: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lieu: Mapped[str | None] = mapped_column(String(255), nullable=True)
    projet_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_projets.id"), nullable=True)
    participants: Mapped[list] = mapped_column(JSON, default=list)
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    points_abordes: Mapped[list] = mapped_column(JSON, default=list)


class KBCrActionModel(Base):
    __tablename__ = "kb_cr_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("kb_compte_rendu.doc_id"), index=True)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsable: Mapped[str | None] = mapped_column(String(255), nullable=True)
    echeance: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    statut: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ── Certification ────────────────────────────────────────────────────────────

class KBCertificationModel(Base, _KBFactCommon):
    __tablename__ = "kb_certification"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    titulaire: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    intitule: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    organisme_emetteur: Mapped[str | None] = mapped_column(String(255), nullable=True)
    numero_identifiant: Mapped[str | None] = mapped_column(String(150), nullable=True)
    date_emission: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_expiration: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    statut: Mapped[str | None] = mapped_column(String(50), nullable=True)
    domaine: Mapped[str | None] = mapped_column(String(150), nullable=True)
    personne_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_personnes.id"), nullable=True)


# ── PV de recette ────────────────────────────────────────────────────────────

class KBPvRecetteModel(Base, _KBFactCommon):
    __tablename__ = "kb_pv_recette"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    projet_associe: Mapped[str | None] = mapped_column(String(500), index=True, nullable=True)
    client: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    type_recette: Mapped[str | None] = mapped_column(String(50), nullable=True)
    statut_global: Mapped[str | None] = mapped_column(String(50), nullable=True)
    projet_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_projets.id"), nullable=True)
    client_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_clients.id"), nullable=True)
    livrables: Mapped[list] = mapped_column(JSON, default=list)
    signataires: Mapped[list] = mapped_column(JSON, default=list)


class KBPvReserveModel(Base):
    __tablename__ = "kb_pv_reserves"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("kb_pv_recette.doc_id"), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticite: Mapped[str | None] = mapped_column(String(50), nullable=True)
    statut: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    date_levee: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ── Attestation de bonne exécution ───────────────────────────────────────────

class KBAttestationModel(Base, _KBFactCommon):
    __tablename__ = "kb_attestation"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    emetteur_client: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    projet_marche: Mapped[str | None] = mapped_column(String(500), index=True, nullable=True)
    montant_valeur: Mapped[float | None] = mapped_column(Float, index=True, nullable=True)
    montant_devise: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_debut: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_fin: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    duree_mois: Mapped[int | None] = mapped_column(Integer, nullable=True)
    niveau_appreciation: Mapped[str | None] = mapped_column(String(150), nullable=True)
    secteur: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    client_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_clients.id"), nullable=True)
    projet_ref_id: Mapped[str | None] = mapped_column(String, ForeignKey("kb_projets.id"), nullable=True)
    perimetre_prestations: Mapped[list] = mapped_column(JSON, default=list)
    signataire: Mapped[dict] = mapped_column(JSON, default=dict)


class PresalesDossierModel(Base):
    """Dossier d'appel d'offres persisté (UC10 Pre-Sales).

    Avant : le fichier AO et tout l'état du workflow (scoring, stratégie, checklist...)
    ne vivaient qu'en mémoire navigateur (localStorage + File en RAM) → après un
    rechargement de page, le File disparaissait et « refaire une étape » échouait
    (« Fichier non disponible »). Ici, le fichier source est écrit sur disque
    (`file_path`) et l'intégralité de l'état (forme `AOEntry` du frontend) est
    répliquée dans `state` (JSON) → toute étape est rejouable à tout moment, y
    compris après reload, tant que le dossier n'a pas été purgé.

    `client_name` / `owner` / `deadline` / `status` sont dupliqués depuis `state`
    à chaque écriture — uniquement pour indexer/filtrer/purger sans désérialiser
    le JSON. `state` reste la seule source de vérité renvoyée au frontend.
    """
    __tablename__ = "presales_dossiers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String(500), default="")
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    client_name: Mapped[str] = mapped_column(String(255), default="")
    owner: Mapped[str] = mapped_column(String(255), default="")
    deadline: Mapped[str] = mapped_column(String(20), default="", index=True)  # "YYYY-MM-DD" ou ""
    status: Mapped[str] = mapped_column(String(30), default="pending_analysis")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KBAliasModel(Base):
    """Journal des libellés observés → entité canonique (Phase 2).

    Sert d'index de recherche normalisé ET de file de revue humaine :
    - status `confirmed` : alias canonique (ou validé par un humain) ;
    - status `auto`      : rapproché automatiquement (score ≥ seuil auto) ;
    - status `pending`   : rapprochement incertain → revue humaine requise
      (`entity_id` = suggestion ; le fait n'est PAS lié tant que non confirmé).
    """
    __tablename__ = "kb_aliases"
    __table_args__ = (Index("ix_kb_alias_type_norm", "entity_type", "alias_norm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20), index=True)   # client | personne | projet
    alias_norm: Mapped[str] = mapped_column(String(500), index=True)
    alias_raw: Mapped[str] = mapped_column(String(500), default="")
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="auto")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    source_doc_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PipelineSnapshotModel(Base):
    """Instantané quotidien append-only d'une opportunité (jamais écrasé, contrairement
    à OpportunityModel). Alimente le moteur M5 (crédibilité/calibrage du pipeline dans
    le temps), impossible à calculer sur un miroir qui ne garde que l'état courant."""
    __tablename__ = "pipeline_snapshots"
    __table_args__ = (Index("ix_pipeline_snapshots_date_opp", "snapshot_date", "opp_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    opp_id: Mapped[str] = mapped_column(String, index=True)
    odoo_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    client_name: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(500))
    stage: Mapped[str] = mapped_column(String(100), default="")
    expected_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    probability: Mapped[float] = mapped_column(Float, default=0.0)
    salesperson_name: Mapped[str] = mapped_column(String(255), default="")
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Recopiée depuis OpportunityModel : sans elle, l'historique accumulé ne serait
    # pas ventilable par famille rétroactivement (le libellé seul suffirait à
    # reclasser, mais la taxonomie évolue — figer la famille du jour préserve la
    # comparabilité dans le temps).
    offer_family: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)


class BacklogSnapshotModel(Base):
    """Instantané quotidien append-only d'un dossier (jamais écrasé, contrairement à
    DossierModel). Alimente le moteur M3 (courbe réelle de facturation vs théorique),
    impossible à reconstituer sur un miroir qui ne garde que la valeur du jour."""
    __tablename__ = "backlog_snapshots"
    __table_args__ = (Index("ix_backlog_snapshots_date_dossier", "snapshot_date", "dossier_ref", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    dossier_ref: Mapped[str] = mapped_column(String(50), index=True)
    client_name: Mapped[str] = mapped_column(String(255), default="")
    salesperson: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="draft")
    backlog: Mapped[float] = mapped_column(Float, default=0.0)
    ca_provisoire: Mapped[float] = mapped_column(Float, default=0.0)
    ca_definitif: Mapped[float] = mapped_column(Float, default=0.0)
    marge_definitive: Mapped[float] = mapped_column(Float, default=0.0)
    montant_recu: Mapped[float] = mapped_column(Float, default=0.0)
    reste_a_encaisser: Mapped[float] = mapped_column(Float, default=0.0)


class DecisionModel(Base):
    """Registre de décisions du module Arbitrages (UC Arbitrage).

    Cette table existait déjà dans la base (prototype antérieur au découpage
    modules/uc_*) avec les colonnes `title`..`decided_at` — on la réutilise
    plutôt que d'en créer une nouvelle : elle contient déjà une décision réelle
    (GO/NO-BID avant-vente). Les colonnes `subject_*`..`review_comment` sont
    ajoutées après coup par `db/database.py::_migrate_decisions`, suivant le
    même principe idempotent que les autres migrations manuelles de ce fichier
    (create_all ne modifie jamais une table existante).

    `status` : en_cours | tranchee | reportee | escaladee | suspendue.
    `review_verdict` : confirme | infirme | partiel | (vide = pas encore revue).
    """
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    context: Mapped[str] = mapped_column(Text, default="")
    decision_type: Mapped[str] = mapped_column(String(50), default="ARBITRAGE")
    status: Mapped[str] = mapped_column(String(50), default="en_cours")
    owner: Mapped[str] = mapped_column(String(255), default="")
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Colonnes ajoutées pour le module Arbitrages (cockpit) :
    subject_ref: Mapped[str] = mapped_column(String(255), default="")
    subject_label: Mapped[str] = mapped_column(String(500), default="")
    enjeu_xof: Mapped[float] = mapped_column(Float, default=0.0)
    cout_report_xof_semaine: Mapped[float] = mapped_column(Float, default=0.0)
    mandat_role: Mapped[str] = mapped_column(String(50), default="")
    profils_impliques: Mapped[list] = mapped_column(JSON, default=list)
    option_retenue: Mapped[str] = mapped_column(Text, default="")
    review_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_verdict: Mapped[str] = mapped_column(String(20), default="")
    review_comment: Mapped[str] = mapped_column(Text, default="")
    # Ce que l'outil RECOMMANDAIT au moment de la décision, distinct de ce qui a
    # été retenu. Sans ce couple, le « taux de confirmation » du module 29 ne
    # mesurait rien d'interprétable : une décision où le mandataire a écarté la
    # recommandation puis réussi y était comptée comme une recommandation vérifiée.
    option_recommandee: Mapped[str] = mapped_column(Text, default="")
    # Motif écrit par le mandataire quand il tranche, reporte ou escalade. Une
    # décision reportée sans motif est indistinguable d'un dossier oublié.
    motif_decision: Mapped[str] = mapped_column(Text, default="")
    # Classe de payeur du client au moment de la décision (cf. uc_arbitrage/payeur.py).
    # Le profil évolue à chaque encaissement : sans figer la lecture qui a servi à
    # trancher, la revue à 30 jours juge la décision sur des faits qui ont changé.
    profil_payeur_classe: Mapped[str] = mapped_column(String(40), default="")


class DailyAnalysisModel(Base):
    """Narration IA d'une section de cockpit, calculée une fois par jour et figée.

    Les endpoints `.../analysis` appelaient Claude à chaque affichage de cockpit
    (10 à 20 s de squelette de chargement), amortis par un simple cache mémoire
    de 15 min — perdu à chaque redémarrage, soit ~96 générations identiques par
    jour et par section. Cette table est le réceptacle du calcul quotidien : le
    job planifié du matin (`jobs/scheduler.py::_daily_analyses_job`) écrit une
    ligne par section, les endpoints ne font plus que la relire.

    `variant` distingue deux lectures d'une même section qui ne doivent jamais
    partager un texte (période affichée pour la tendance CA, exercice pour les
    marges) ; vide quand la section n'a qu'une seule lecture possible.

    `source` : "llm" (rédigé par Claude) | "repli" (repli déterministe des
    `build_*_analysis`). Seul un "llm" est enregistré — figer un repli produit
    pendant une indisponibilité du modèle ferait durer l'incident toute la
    journée (même principe que le `store_if` de core/services/ttl_cache.py).
    """
    __tablename__ = "daily_analyses"
    __table_args__ = (
        Index(
            "ix_daily_analyses_key_variant_date",
            "analysis_key", "variant", "snapshot_date",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_key: Mapped[str] = mapped_column(String(60), index=True)
    variant: Mapped[str] = mapped_column(String(160), default="")
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    analysis: Mapped[str] = mapped_column(Text, default="")
    # Chiffres réels passés au modèle — conservés pour pouvoir vérifier après coup
    # sur quoi le texte figé s'appuyait (les agrégats bougent avec la sync Odoo).
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(20), default="llm")
    triggered_by: Mapped[str] = mapped_column(String(20), default="schedule")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ArbitrageContexteModel(Base):
    """Contexte terrain d'un dossier d'arbitrage — la contribution du commercial
    du compte, saisie AVANT que le dossier soit tranché.

    Le dossier demande explicitement « motif du retard de paiement — seul un
    appel client le donnerait, owner : Compte » (cf.
    uc_arbitrage/aggregation.py::missing_info). Il n'existait aucun endroit pour
    déposer la réponse : l'écran formulait une demande à l'account manager sans
    réceptacle, et celui qui détient l'information décisive n'avait aucune
    surface d'action. Cette table est ce réceptacle.

    Rattachée au `subject_ref` (nom du client) et non à une décision : le
    contexte existe avant la décision, et sert précisément à la préparer.
    """
    __tablename__ = "arbitrage_contextes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_ref: Mapped[str] = mapped_column(String(255), index=True)
    # Motif du retard tel que rapporté par le terrain — texte libre assumé : c'est
    # une parole d'account manager, pas une donnée à normaliser.
    motif_retard: Mapped[str] = mapped_column(Text, default="")
    # Le dossier commercial est-il toujours d'actualité côté client ? Deuxième
    # question posée par `missing_info`, à laquelle seul le terrain peut répondre.
    dossier_toujours_actif: Mapped[str] = mapped_column(String(20), default="")
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_role: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ArbitrageNarrationModel(Base):
    """Parties rédigées d'un dossier d'arbitrage — avocat du contraire et
    formulation de l'option C (cf. uc_arbitrage/narratif.py).

    Ces deux textes coûtent un appel Claude Sonnet chacun, soit ~5 s mesurées à
    l'ouverture d'un dossier. Ils étaient amortis par le cache mémoire de
    `core/services/ttl_cache.py`, qui porte deux limites que ce module ne
    supporte plus :

      - il est PROCESS-LOCAL, et l'API tourne avec `--workers 2` (cf.
        Dockerfile) : chaque worker payait sa propre génération, et un
        redéploiement les remettait tous les deux à zéro ;
      - sa fenêtre de 900 s expirait alors même qu'aucun chiffre cité n'avait
        bougé — la narration était réécrite à l'identique, pour rien.

    La clé n'est donc PAS une date ni une durée mais `empreinte` : le sha256 de
    tout ce que les deux gabarits de prompt consomment réellement
    (`narratif._empreinte`). Une ligne reste valable tant que le dossier dit la
    même chose, et devient inatteignable dès qu'un montant, une lecture de
    payeur, un échéancier ou un verdict de revue change — l'invalidation est
    portée par le contenu, pas par une horloge.

    Seule une rédaction entièrement produite par le modèle est enregistrée : un
    repli déterministe (modèle indisponible) doit rester recalculable, sinon
    une panne de quelques secondes se fige en base. Même règle que le `store_if`
    de ttl_cache et que `uc_daily_analysis.store.est_figeable`.
    """
    __tablename__ = "arbitrage_narrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # sha256 hex de l'empreinte du dossier — 64 caractères, unique.
    empreinte: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Redondant avec l'empreinte, mais c'est la seule colonne lisible à l'œil :
    # sans elle, la table est un mur de hashs impossible à inspecter en prod.
    subject_ref: Mapped[str] = mapped_column(String(255), index=True)
    # {"raisons": [...], "redaction": {...} | null} — la forme rendue par
    # `narratif.build_dossier_narration`, stockée telle quelle.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ArbitrageParamModel(Base):
    """Réglages du module Arbitrages, en JSON sous clé — même forme que
    `commercial_params`.

    Une seule clé aujourd'hui : `conditions_par_profil`, qui porte les
    conditions d'entrée en arbitrage activées par chaque profil
    (`{"dg": ["impaye_superieur_enjeu", ...], ...}`).

    Ce ne sont PAS les conditions elles-mêmes : celles-ci vivent dans le code
    (`uc_arbitrage/conditions.py`), écrites, seuillées et testées une fois pour
    toutes. Cette table ne porte que l'ACTIVATION — quel profil a coché quoi.
    La distinction est délibérée : une condition d'entrée en arbitrage décide de
    ce qui est soumis à décision, elle doit rester relisible dans le code et
    couverte par des tests, pas rédigée à l'écran par un utilisateur.

    L'absence de ligne (ou un profil absent du JSON) vaut « aucune condition
    active » : la file reste alors celle du socle, c'est-à-dire le comportement
    d'avant ce réglage. Aucun écran ne change tant que personne n'a coché.
    """
    __tablename__ = "arbitrage_params"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_by: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Pilotage commercial (UC Commercial — cockpit DC)
#
# Ces six tables PRÉEXISTAIENT en base sans modèle correspondant dans ce
# fichier : elles avaient été créées par un code depuis disparu (il ne reste que
# du bytecode dans modules/uc_commercial/__pycache__, daté du 04/08/2026, jamais
# committé). Les colonnes déclarées ici reproduisent EXACTEMENT le schéma trouvé
# en base — `create_all` ne modifie jamais une table existante, un écart de
# colonne se traduirait donc par une erreur SQL au premier accès, pas par une
# migration.
#
# Elles portent ce qu'aucun fait du miroir Odoo ne peut fournir : un objectif est
# une DÉCISION (pas une donnée synchronisée), un référentiel de commerciaux est
# un ARBITRAGE d'identité (Odoo ne stocke que du texte libre), un axe stratégique
# est une GRILLE DE LECTURE (« IA », « infrastructure » n'existent nulle part
# dans le CRM).
# ─────────────────────────────────────────────────────────────────────────────


class CommercialObjectiveModel(Base):
    """Objectif commercial — la donnée qui manquait à tout indicateur d'écart.

    `scope`/`scope_ref` : "equipe" (ref vide), "commercial" (ref = salesperson_id),
    "secteur" (ref = libellé secteur). `kind` : "ca" (montant signé) ou "prospection"
    (opportunités générées). Les deux cibles coexistent sur une ligne car le DC les
    exprime ensemble (« 30 M et tant de leads ») : `target_amount_xof` peut être 0
    sur un objectif de volume pur, et `target_count` 0 sur un objectif de montant pur.

    `period_index` : 1-12 en mensuel, 1-4 en trimestriel, 0 en annuel.

    RÉVISIONS : un objectif n'est jamais mis à jour en place — on insère une
    révision supérieure et on marque la précédente `superseded`. Sans cela, un Gap
    calculé en mars n'est plus reproductible après une révision de juin, et le
    « pourquoi » de l'écart devient indéfendable.
    """
    __tablename__ = "commercial_objectives"
    __table_args__ = (
        Index("ix_commercial_objectives_lookup", "scope", "scope_ref", "kind", "period_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), default="equipe")
    scope_ref: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(20), default="ca")
    period_type: Mapped[str] = mapped_column(String(10), default="annee")
    period_year: Mapped[int] = mapped_column(Integer, default=0)
    period_index: Mapped[int] = mapped_column(Integer, default=0)
    target_amount_xof: Mapped[float] = mapped_column(Float, default=0.0)
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommercialAlertModel(Base):
    """Alerte du cockpit commercial, persistée pour porter son ÂGE.

    Le calcul des signaux est refait à chaque lecture (aucune heuristique n'est
    figée en base) ; ce qui est persisté, c'est la date de PREMIÈRE apparition
    d'une clé et l'éventuel écartement. Deux raisons :

    - « ce compte est en pic depuis 3 jours » n'est pas calculable sur un miroir
      qui ne garde que l'état courant. `created_at` de la clé le donne ;
    - une alerte écartée qui revient chaque matin est du bruit, exactement ce que
      le DC redoute. `dismissed_at` la retire, `dismissed_reason` dit pourquoi.

    `alert_key` est DÉTERMINISTE (type + sujet + période), jamais un hash aléatoire :
    c'est ce qui permet de reconnaître la même alerte d'un jour sur l'autre.
    """
    __tablename__ = "commercial_alerts"
    __table_args__ = (Index("ix_commercial_alerts_key", "alert_key", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_key: Mapped[str] = mapped_column(String(255))
    alert_type: Mapped[str] = mapped_column(String(40), default="")
    severity: Mapped[str] = mapped_column(String(20), default="info")
    subject_ref: Mapped[str] = mapped_column(String(255), default="")
    subject_label: Mapped[str] = mapped_column(String(500), default="")
    salesperson_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    montant_xof: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dismissed_reason: Mapped[str] = mapped_column(String(500), default="")


class CommercialParamModel(Base):
    """Paramètres métier du cockpit commercial (seuils), en JSON sous clé.

    Les seuils de dormance sont, eux, VALIDÉS et donc figés dans le code
    (uc_dormance). Cette table ne porte que ce qui reste ouvert : seuil de
    traçage du cycle de vie, sensibilité de la détection de pic, règle de
    complétude d'une opportunité. Un seuil arbitraire codé en dur se lit comme
    une vérité métier ; sous clé paramétrable, il reste discutable.
    """
    __tablename__ = "commercial_params"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_by: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BriefingPreferenceModel(Base):
    """Composition du débrief quotidien, décidée PAR RÔLE (pas par utilisateur).

    Portée assumée : le briefing est déjà généré par rôle (un `sections[role]`
    unique dans le store) et lu par tous les porteurs de ce rôle. Une préférence
    par utilisateur imposerait d'en générer autant que de comptes, pour un coût
    LLM qu'aucun usage ne réclame — S2I compte un titulaire par direction.

    Pourquoi une table et pas le store JSON : data/briefing_store/latest.json est
    un CACHE JETABLE, supprimé par scripts/purge_partenaires_exclus.py et réécrit
    intégralement à chaque `service.generate`. Une préférence qui y vivrait
    disparaîtrait à la première purge, sans trace ni message.

    Table vide = comportement d'origine (le catalogue par défaut s'applique),
    même doctrine que ModulePermissionModel où l'absence de ligne signifie
    « défauts du code » : rien à migrer, rien à initialiser.

    `value_json` est un blob et non des colonnes typées parce que le projet n'a
    pas d'Alembic (db/database.py::init_db fait create_all + des _migrate_*
    manuels) : y ajouter un champ ne doit pas coûter une migration.
    """
    __tablename__ = "briefing_preferences"

    role: Mapped[str] = mapped_column(String(50), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    # Le réglage est PARTAGÉ : un DG qui trouve son débrief changé doit pouvoir
    # savoir qui l'a changé. C'est la contrepartie obligatoire de la portée par rôle.
    updated_by: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalespersonModel(Base):
    """Identité commerciale canonique — ce qu'Odoo ne porte pas.

    Le miroir ne connaît que `salesperson_name` en texte libre : 28 valeurs
    distinctes dans `opportunities`, 36 dans `sale_orders`, avec des doublons de
    casse (« Segui Mireille  KOUADIO » / « SEGUI MIREILLE  KOUADIO ») et des
    comptes techniques (« Administrateur » porte 1 106 opportunités). Sans cette
    table, tout classement par commercial additionne des orthographes et compte
    un robot parmi les vendeurs.

    `is_active`/`left_at` : un commercial parti ne doit pas disparaître de
    l'historique, seulement des classements de la période courante.
    """
    __tablename__ = "salespeople"

    salesperson_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odoo_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalespersonAliasModel(Base):
    """Orthographe observée dans le miroir → identité canonique.

    `confirmed = False` signale un rattachement PROPOSÉ par la normalisation
    automatique (casse, espaces, accents) et non validé humainement. Le cockpit
    doit dire combien d'alias restent non confirmés : c'est la marge d'erreur du
    classement, et la taire reviendrait à présenter un palmarès comme certain.

    `salesperson_id` nul = alias volontairement non rattaché (compte technique,
    assistante commerciale, entité interne) : une exclusion assumée et tracée,
    pas une donnée perdue.
    """
    __tablename__ = "salesperson_aliases"
    __table_args__ = (Index("ix_salesperson_aliases_norm", "alias_normalized", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias_normalized: Mapped[str] = mapped_column(String(255))
    alias_raw: Mapped[str] = mapped_column(String(255), default="")
    salesperson_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_tables: Mapped[list] = mapped_column(JSON, default=list)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_by: Mapped[str] = mapped_column(String(255), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StrategicAxisMappingModel(Base):
    """Motif de libellé → axe stratégique (« IA », « infrastructure », « cloud »…).

    Le DC raisonne en marchés (« santé du marché orienté IA et infrastructure »),
    le CRM ne porte ni secteur exploitable ni catégorie d'offre. Cette table est
    la grille de lecture qui relie les deux, en assumant qu'elle est une
    CONVENTION éditable et non une vérité extraite des données.

    Distincte de la taxonomie de familles d'offre (uc_offermix), qui répond à
    « qu'est-ce qu'on vend » (logiciel / réseau / équipement / services). Ici la
    question est « sur quel marché » — un même équipement peut relever de l'axe
    datacenter ou de l'axe cybersécurité selon le projet.
    """
    __tablename__ = "strategic_axis_mappings"
    __table_args__ = (Index("ix_strategic_axis_mappings_axis", "axis"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    axis: Mapped[str] = mapped_column(String(50), default="")
    match_type: Mapped[str] = mapped_column(String(20), default="contains")
    pattern: Mapped[str] = mapped_column(String(255), default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
