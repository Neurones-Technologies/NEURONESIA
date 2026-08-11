import logging

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config.settings import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.local_db_path}",
    echo=False,  # Jamais True — coût +3-10ms/requête + saturation logs
    connect_args={"timeout": 30, "check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")       # Concurrent reads + non-blocking writes
    cur.execute("PRAGMA synchronous=NORMAL")      # Sécurité raisonnable, 3x plus rapide que FULL
    cur.execute("PRAGMA cache_size=-64000")       # 64 MB de cache page
    cur.execute("PRAGMA busy_timeout=30000")      # Attendre 30s avant SQLITE_BUSY
    cur.execute("PRAGMA temp_store=MEMORY")       # Tri/agrégats en mémoire
    cur.execute("PRAGMA mmap_size=134217728")     # 128 MB memory-mapped I/O
    cur.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    settings.local_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_veille_entries)
        await conn.run_sync(_migrate_sale_orders)
        await conn.run_sync(_migrate_opportunities)
        await conn.run_sync(_migrate_pipeline_snapshots)
        await conn.run_sync(_migrate_purchase_orders)
        await conn.run_sync(_migrate_decisions)
        await conn.run_sync(_migrate_conversations)


# Colonnes IA S2I ajoutées après coup au Watch-Tracker. `create_all` ne modifie
# jamais une table existante → on ajoute les colonnes manquantes à la main, de
# façon idempotente (aucun effet si la base est déjà à jour ou fraîchement créée).
_VEILLE_ENTRY_NEW_COLUMNS = {
    "ai_analyzed": "BOOLEAN NOT NULL DEFAULT 0",
    "signal_label": "VARCHAR(255) NOT NULL DEFAULT ''",
    "risque": "VARCHAR(500) NOT NULL DEFAULT ''",
    "offre": "VARCHAR(500) NOT NULL DEFAULT ''",
    "offre_short": "VARCHAR(100) NOT NULL DEFAULT ''",
    "priority": "VARCHAR(20) NOT NULL DEFAULT ''",
    "criticite": "INTEGER NOT NULL DEFAULT 0",
    "organisation": "VARCHAR(255) NOT NULL DEFAULT ''",
    "justification": "VARCHAR(1000) NOT NULL DEFAULT ''",
    "origin": "VARCHAR(20) NOT NULL DEFAULT 'source'",
    "debrief": "TEXT NOT NULL DEFAULT ''",
}


def _migrate_veille_entries(sync_conn):
    inspector = inspect(sync_conn)
    if "veille_entries" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("veille_entries")}
    for name, ddl in _VEILLE_ENTRY_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE veille_entries ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration veille_entries : colonne '%s' ajoutée", name)


# Lien commande → factures (sale.order.invoice_ids), ajouté après coup pour
# rattacher les factures réelles à leur bon de commande d'origine.
_SALE_ORDER_NEW_COLUMNS = {
    "invoice_ids": "JSON NOT NULL DEFAULT '[]'",
}


def _migrate_sale_orders(sync_conn):
    inspector = inspect(sync_conn)
    if "sale_orders" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("sale_orders")}
    for name, ddl in _SALE_ORDER_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE sale_orders ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration sale_orders : colonne '%s' ajoutée", name)


# Lien opportunité → bons de commande générés (crm.lead.order_ids), pour
# tracer quelle vente a réellement découlé de quelle opportunité du pipeline.
# `offer_family` : famille d'offre déduite du libellé (cf. uc_offermix.taxonomy),
# NULL tant qu'un libellé ne permet pas de trancher — nullable assumé, c'est ce
# NULL qui alimente le taux de couverture affiché au Directeur Commercial.
_OPPORTUNITY_NEW_COLUMNS = {
    "order_ids": "JSON NOT NULL DEFAULT '[]'",
    "offer_family": "VARCHAR(30)",
}


def _migrate_opportunities(sync_conn):
    inspector = inspect(sync_conn)
    if "opportunities" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("opportunities")}
    for name, ddl in _OPPORTUNITY_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE opportunities ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration opportunities : colonne '%s' ajoutée", name)
    # `create_all` ne touche pas aux index d'une table existante.
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_opportunities_offer_family "
        "ON opportunities (offer_family)"
    )


# Même colonne sur l'instantané quotidien : sans elle l'historique accumulé ne
# serait pas ventilable par famille.
_PIPELINE_SNAPSHOT_NEW_COLUMNS = {
    "offer_family": "VARCHAR(30)",
}


def _migrate_pipeline_snapshots(sync_conn):
    inspector = inspect(sync_conn)
    if "pipeline_snapshots" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("pipeline_snapshots")}
    for name, ddl in _PIPELINE_SNAPSHOT_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE pipeline_snapshots ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration pipeline_snapshots : colonne '%s' ajoutée", name)
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_pipeline_snapshots_offer_family "
        "ON pipeline_snapshots (offer_family)"
    )


# Lien commande fournisseur → dossier (purchase.order.dossier_id) — ajouté après coup
# pour rattacher un achat à la marge réelle de la mission qu'il a servie (indicateur
# "marge de sous-traitance", cf. get_supplier_intelligence dans local_crm_adapter.py).
_PURCHASE_ORDER_NEW_COLUMNS = {
    "dossier_id": "VARCHAR(255)",
}


def _migrate_purchase_orders(sync_conn):
    inspector = inspect(sync_conn)
    if "purchase_orders" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("purchase_orders")}
    for name, ddl in _PURCHASE_ORDER_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE purchase_orders ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration purchase_orders : colonne '%s' ajoutée", name)


# Table `decisions` : prototype antérieur (title..decided_at déjà en base, avec
# une décision réelle) réutilisé pour le module Arbitrages du cockpit — on lui
# ajoute les colonnes de suivi d'enjeu/mandat/revue qui lui manquaient.
_DECISION_NEW_COLUMNS = {
    "subject_ref": "VARCHAR(255) NOT NULL DEFAULT ''",
    "subject_label": "VARCHAR(500) NOT NULL DEFAULT ''",
    "enjeu_xof": "FLOAT NOT NULL DEFAULT 0",
    "cout_report_xof_semaine": "FLOAT NOT NULL DEFAULT 0",
    "mandat_role": "VARCHAR(50) NOT NULL DEFAULT ''",
    "profils_impliques": "JSON NOT NULL DEFAULT '[]'",
    "option_retenue": "TEXT NOT NULL DEFAULT ''",
    "review_date": "DATETIME",
    "review_verdict": "VARCHAR(20) NOT NULL DEFAULT ''",
    "review_comment": "TEXT NOT NULL DEFAULT ''",
    # Recommandation de l'outil au moment de trancher, motif du mandataire, et
    # classe de payeur qui a servi de lecture — cf. DecisionModel pour le détail
    # de ce que chacune de ces trois colonnes rend enfin mesurable.
    "option_recommandee": "TEXT NOT NULL DEFAULT ''",
    "motif_decision": "TEXT NOT NULL DEFAULT ''",
    "profil_payeur_classe": "VARCHAR(40) NOT NULL DEFAULT ''",
}


def _migrate_decisions(sync_conn):
    inspector = inspect(sync_conn)
    if "decisions" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("decisions")}
    for name, ddl in _DECISION_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE decisions ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration decisions : colonne '%s' ajoutée", name)


# Historique du Copilote cloisonné par profil cockpit — colonne ajoutée après
# coup. Les conversations antérieures gardent profile='' : elles restent en base
# (et purgées à 30 jours comme les autres) mais ne remontent dans aucune des cinq
# listes, faute de savoir depuis quel profil elles ont été menées.
_CONVERSATION_NEW_COLUMNS = {
    "profile": "VARCHAR(20) NOT NULL DEFAULT ''",
}


def _migrate_conversations(sync_conn):
    inspector = inspect(sync_conn)
    if "conversations" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("conversations")}
    for name, ddl in _CONVERSATION_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE conversations ADD COLUMN {name} {ddl}"
            )
            logger.info("Migration conversations : colonne '%s' ajoutée", name)
    # `create_all` ne touche pas aux index d'une table existante : on crée
    # explicitement celui qui couvre la liste des conversations.
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_conv_user_profile_time "
        "ON conversations (user_id, profile, created_at)"
    )


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
