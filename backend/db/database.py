import logging

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config.settings import settings
from core.services.constructeurs import vendor_a_persister

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
        # AVANT l'amorçage : celui-ci écrit `vendor`, la colonne doit exister.
        await conn.run_sync(_migrate_sale_order_lines)
        # En dernier : lit sale_orders (colonnes ajoutées juste au-dessus) pour
        # amorcer sale_order_lines sans attendre une synchro Odoo complète.
        await conn.run_sync(_backfill_sale_order_lines)


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
    # Lecture marché du signal, lue par uc_commercial.fetch_veille : sentinelle ""
    # et non NULL, le taux de remplissage d'`axe` étant servi comme taux de
    # couverture de la veille.
    "axe": "VARCHAR(100) NOT NULL DEFAULT ''",
    "so_what": "VARCHAR(1000) NOT NULL DEFAULT ''",
    "action_suggeree": "VARCHAR(1000) NOT NULL DEFAULT ''",
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
#
# `amount_untaxed` : base HT de la commande. `amount` porte l'amount_total (TTC) ;
# sans la base HT, toute comparaison avec la somme des lignes — elles aussi HT —
# affiche un faux écart de 18 % (TVA CI).
#
# `purchase_total` / `margin_amount` / `margin_pct` : coût d'achat et marge portés
# par Odoo (« Total Achats », « Marge Totale », « Marge Global » de la vue devis),
# jamais synchronisés jusqu'ici. Défaut 0.0 : une instance Odoo sans module de
# marge laisse ces colonnes à zéro, ce qui n'est pas « marge nulle » mais « marge
# inconnue » — cf. le commentaire du modèle.
_SALE_ORDER_NEW_COLUMNS = {
    "invoice_ids": "JSON NOT NULL DEFAULT '[]'",
    "amount_untaxed": "FLOAT NOT NULL DEFAULT 0.0",
    "purchase_total": "FLOAT NOT NULL DEFAULT 0.0",
    "approach_costs": "FLOAT NOT NULL DEFAULT 0.0",
    "provision": "FLOAT NOT NULL DEFAULT 0.0",
    "margin_amount": "FLOAT NOT NULL DEFAULT 0.0",
    "margin_pct": "FLOAT NOT NULL DEFAULT 0.0",
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


# `vendor` : constructeur déduit du libellé (cf. core/services/constructeurs.py).
# NOT NULL DEFAULT '' et non NULL : "" signifie « le référentiel a tourné et n'a rien
# pu décider », ce qui n'est pas la même information que « jamais soumis au
# référentiel ». Sur une base existante, l'ALTER pose donc "" partout et c'est
# `scripts/reclasser_constructeurs.py` qui remplit — sans quoi une colonne à moitié
# vide se lirait comme « ces lignes n'ont pas de constructeur », un contresens.
_SALE_ORDER_LINE_NEW_COLUMNS = {
    "vendor": "VARCHAR(60) NOT NULL DEFAULT ''",
}


def _migrate_sale_order_lines(sync_conn):
    inspector = inspect(sync_conn)
    if "sale_order_lines" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("sale_order_lines")}
    ajoutees = False
    for name, ddl in _SALE_ORDER_LINE_NEW_COLUMNS.items():
        if name not in existing:
            sync_conn.exec_driver_sql(
                f"ALTER TABLE sale_order_lines ADD COLUMN {name} {ddl}"
            )
            ajoutees = True
            logger.info("Migration sale_order_lines : colonne '%s' ajoutée", name)
    # `create_all` ne touche pas aux index d'une table existante : l'index de
    # `vendor` porte le GROUP BY de toute analyse par constructeur.
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_sale_order_lines_vendor "
        "ON sale_order_lines (vendor)"
    )
    if ajoutees:
        restant = sync_conn.exec_driver_sql(
            "SELECT COUNT(*) FROM sale_order_lines WHERE vendor = ''"
        ).scalar()
        if restant:
            logger.warning(
                "sale_order_lines : %d ligne(s) sans constructeur — lancer "
                "`python -m scripts.reclasser_constructeurs --apply` pour les "
                "classer, sinon toute analyse par marque les comptera comme "
                "non attribuées",
                restant,
            )


# Lien opportunité → bons de commande générés (crm.lead.order_ids), pour
# tracer quelle vente a réellement découlé de quelle opportunité du pipeline.
# `offer_family` : famille d'offre déduite du libellé (cf. uc_offermix.taxonomy),
# NULL tant qu'un libellé ne permet pas de trancher — nullable assumé, c'est ce
# NULL qui alimente le taux de couverture affiché au Directeur Commercial.
# `date_closed`/`write_date` : datation du cycle de vente, lues par
# uc_commercial.fetch_opportunites. Nullable sans défaut — une date inventée
# fausserait la durée de cycle ; elles restent vides jusqu'à la prochaine sync
# Odoo, qui les renseigne depuis crm.lead.
_OPPORTUNITY_NEW_COLUMNS = {
    "order_ids": "JSON NOT NULL DEFAULT '[]'",
    "offer_family": "VARCHAR(30)",
    "date_closed": "DATETIME",
    "write_date": "DATETIME",
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


def _backfill_sale_order_lines(sync_conn):
    """Amorce `sale_order_lines` depuis le JSON `sale_orders.order_lines`.

    Sans cela la table resterait vide jusqu'à la première synchro Odoo complète,
    et toutes les analyses produit basculeraient d'un coup sur zéro ligne — une
    régression pire que le blob qu'on remplace.

    Ne fait rien si la table contient déjà des lignes : c'est un amorçage unique,
    pas une resynchronisation. Les identifiants produits ici sont SYNTHÉTIQUES
    (`<order_id>#<rang>`), le JSON ne portant pas les ids Odoo des lignes ; la
    synchro Odoo purge les lignes d'une commande avant de les réécrire avec leurs
    vrais ids, donc ces lignes d'amorçage disparaissent au premier passage.

    Deux approximations, toutes deux signalées en base et corrigées par la synchro :

    - conversion de devise : le JSON stocke les montants dans la devise de la
      commande et les taux vivent dans Odoo, inaccessibles hors ligne. Pour une
      commande non-XOF on DÉDUIT le taux de la commande elle-même
      (`amount` / Σ lignes) et on marque `fx_status='derived'`. Σ(subtotal_xof)
      retombe alors sur le TTC, soit jusqu'à +18 % sur une commande taxée —
      largement préférable à un montant en USD compté comme des XOF (facteur 600).
    - `display_type` : absent du JSON. Une ligne dont quantité, prix unitaire ET
      sous-total sont nuls est traitée comme une section de devis. Le test porte
      bien sur les trois champs : une ligne d'acompte a une quantité nulle mais un
      prix unitaire renseigné, et c'est une vraie ligne.

    `vendor` est renseigné ici et non laissé à un traitement ultérieur : une ligne
    écrite sans constructeur serait indistinguable d'une ligne dont le libellé ne
    permet pas de trancher, et toute analyse par marque la compterait en non
    attribuée sans jamais la reclasser.
    """
    import json as _json
    from datetime import datetime as _datetime

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "sale_order_lines" not in tables or "sale_orders" not in tables:
        return
    already = sync_conn.exec_driver_sql("SELECT COUNT(*) FROM sale_order_lines").scalar()
    if already:
        return

    # Partenaires intra-groupe exclus : `sale_orders` peut encore les porter (miroir
    # antérieur à la purge, cf. scripts/purge_partenaires_exclus.py) et un amorçage
    # sans filtre les réinjecterait dans la table même qu'interrogent les analyses
    # par produit — un seul BDC exclu suffit à retourner un classement, c'est le
    # motif de l'exclusion. Filtre et purge se complètent : le filtre empêche
    # l'écriture, la purge nettoie l'existant.
    exclus = [str(i) for i in sorted(settings.excluded_partner_odoo_ids)]
    requete = (
        "SELECT order_id, odoo_id, name, client_id, client_name, date_order, state, "
        "       salesperson_name, amount, currency, order_lines "
        "FROM sale_orders WHERE order_lines IS NOT NULL AND order_lines NOT IN ('', '[]')"
    )
    if exclus:
        requete += " AND COALESCE(client_id, '') NOT IN (" + ",".join("?" * len(exclus)) + ")"
        rows = sync_conn.exec_driver_sql(requete, tuple(exclus)).fetchall()
    else:
        rows = sync_conn.exec_driver_sql(requete).fetchall()

    # `synced_at` est NOT NULL et son défaut est porté par l'ORM (default=utcnow),
    # jamais par le moteur : un INSERT en SQL brut doit fournir la valeur lui-même.
    # Format aligné sur celui que le dialecte SQLite de SQLAlchemy sait relire.
    now = _datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")

    payload: list[tuple] = []
    n_derived = 0
    for (order_id, odoo_id, name, client_id, client_name, date_order, state,
         salesperson, amount, currency, raw_lines) in rows:
        try:
            lines = _json.loads(raw_lines) or []
        except (TypeError, ValueError):
            continue
        if not isinstance(lines, list):
            continue
        total_src = sum(float(ln.get("subtotal") or 0) for ln in lines if isinstance(ln, dict))
        if not currency or currency == "XOF" or total_src <= 0:
            rate, fx_status = 1.0, "exact"
        else:
            rate, fx_status = (amount or 0.0) / total_src, "derived"
            n_derived += 1
        for rank, ln in enumerate(lines):
            if not isinstance(ln, dict):
                continue
            qty = float(ln.get("qty") or 0)
            subtotal = float(ln.get("subtotal") or 0)
            unit = float(ln.get("unit_price") or 0)
            produit = (ln.get("product") or "")[:500]
            code = ln.get("product_code") or ""
            payload.append((
                f"{order_id}#{rank}", None, order_id, name or "", client_id or "",
                client_name or "", date_order, state or "sale", salesperson or "",
                None, code, produit,
                ln.get("product_category") or "",
                "line_section" if (qty == 0 and subtotal == 0 and unit == 0) else None,
                qty, 0.0, 0.0, unit * rate, subtotal * rate, unit, subtotal,
                currency or "XOF", fx_status, 0.0,
                vendor_a_persister(produit, code), now,
            ))

    if not payload:
        return
    sync_conn.exec_driver_sql(
        "INSERT INTO sale_order_lines ("
        "  line_id, odoo_id, order_id, order_name, client_id, client_name, date_order,"
        "  state, salesperson_name, product_id, product_code, product_name,"
        "  product_category, display_type, qty, qty_delivered, qty_invoiced,"
        "  unit_price_xof, subtotal_xof, unit_price_src, subtotal_src, currency_src,"
        "  fx_status, purchase_price_xof, vendor, synced_at"
        ") VALUES (" + ",".join(["?"] * 26) + ")",
        payload,
    )
    n_sans_vendor = sum(1 for p in payload if not p[24])
    logger.info(
        "Amorçage sale_order_lines : %d lignes issues du JSON (%d commandes à taux "
        "déduit, corrigées à la prochaine synchro Odoo ; %d lignes sans constructeur "
        "identifiable)",
        len(payload), n_derived, n_sans_vendor,
    )
