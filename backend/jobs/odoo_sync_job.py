import json
import logging
from datetime import datetime

from adapters.crm.odoo_adapter import OdooAdapter
from db.database import AsyncSessionLocal
from db.models import (
    ClientModel, InvoiceModel, ProjectModel, SaleOrderModel, PurchaseOrderModel,
    OpportunityModel, DossierModel, SupplierModel, SupplierInvoiceModel,
)
from sqlalchemy import select, text
from config.settings import settings

logger = logging.getLogger(__name__)

_LAST_SYNC_FILE = settings.local_db_path.parent / "last_sync.json"


def _load_last_sync() -> datetime | None:
    try:
        if _LAST_SYNC_FILE.exists():
            data = json.loads(_LAST_SYNC_FILE.read_text())
            ts = data.get("last_sync_at")
            if ts:
                return datetime.fromisoformat(ts)
    except (IOError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Impossible de charger last_sync.json : %s", e)
    return None


def _parse_date(raw: str | None) -> datetime | None:
    """Convertit une chaîne date Odoo en datetime. Retourne None si invalide."""
    if not raw or len(raw) < 10:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        logger.warning("Date invalide ignorée : %r", raw)
        return None


def _get_odoo_name(field: list | None, default: str = "") -> str:
    """Extrait le nom (index 1) d'un tuple Odoo [id, name]. Protégé contre None et longueur < 2."""
    if not field or len(field) < 2:
        return default
    return field[1] or default


def _save_last_sync(ts: datetime):
    try:
        _LAST_SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_SYNC_FILE.write_text(json.dumps({"last_sync_at": ts.isoformat()}))
    except Exception as e:
        logger.warning("Impossible de sauvegarder last_sync : %s", e)


async def sync_records_by_id(model: str, odoo_ids: list[int]):
    """
    Sync ciblé par IDs — utilisé par le webhook.
    Récupère uniquement les enregistrements concernés depuis Odoo et met à jour SQLite.
    """
    if not odoo_ids:
        return
    odoo = OdooAdapter()
    try:
        if model == "sale.order":
            await _sync_sale_orders_by_ids(odoo, odoo_ids)
        elif model == "account.move":
            await _sync_invoices_by_ids(odoo, odoo_ids)
            await _sync_supplier_invoices_by_ids(odoo, odoo_ids)
        elif model == "res.partner":
            await _sync_clients_by_ids(odoo, odoo_ids)
            await _sync_suppliers_by_ids(odoo, odoo_ids)
        elif model == "purchase.order":
            await _sync_purchase_orders_by_ids(odoo, odoo_ids)
        else:
            logger.warning("Modèle webhook non géré : %s", model)
    finally:
        await odoo.close()


async def _sync_clients_by_ids(odoo: OdooAdapter, ids: list[int]):
    records = await odoo._call(
        "res.partner", "search_read",
        [[["id", "in", ids]]],
        {"fields": ["id", "name", "email", "phone", "city", "country_id", "industry_id"]},
    )
    async with AsyncSessionLocal() as session:
        for r in records:
            client_id = str(r["id"])
            sector = _get_odoo_name(r.get("industry_id"))
            country = _get_odoo_name(r.get("country_id"))
            existing = await session.get(ClientModel, client_id)
            if existing:
                existing.name = r["name"]
                existing.sector = sector or None
                existing.contact_email = r.get("email") or None
                existing.phone = r.get("phone") or None
                existing.city = r.get("city") or None
                existing.country = country or None
                existing.synced_at = datetime.utcnow()
            else:
                session.add(ClientModel(
                    client_id=client_id, odoo_id=r["id"], name=r["name"],
                    sector=sector or None, contact_email=r.get("email") or None,
                    phone=r.get("phone") or None, city=r.get("city") or None,
                    country=country or None,
                ))
        await session.commit()
    logger.info("Webhook : %d clients mis à jour", len(records))


async def _sync_invoices_by_ids(odoo: OdooAdapter, ids: list[int]):
    rates = await _get_xof_rates(odoo)
    records = await odoo._call(
        "account.move", "search_read",
        [[["id", "in", ids], ["move_type", "=", "out_invoice"]]],
        {"fields": ["id", "name", "partner_id", "amount_total", "amount_residual",
                    "currency_id", "invoice_date", "invoice_date_due", "payment_state"]},
    )
    from adapters.crm.odoo_adapter import OdooAdapter as _OA
    async with AsyncSessionLocal() as session:
        for r in records:
            inv = _OA._move_to_invoice(r, str((r.get("partner_id") or [0])[0]))
            amount_xof = _to_xof(inv.amount, inv.currency, rates)
            residual_xof = _to_xof(float(r.get("amount_residual") or 0), inv.currency, rates)
            existing = await session.get(InvoiceModel, inv.invoice_id)
            if existing:
                existing.status = inv.status.value
                existing.amount = amount_xof
                existing.amount_residual = residual_xof
                existing.synced_at = datetime.utcnow()
                if inv.invoice_date and not existing.invoice_date:
                    existing.invoice_date = inv.invoice_date
                if inv.invoice_name and not existing.invoice_name:
                    existing.invoice_name = inv.invoice_name
            else:
                session.add(InvoiceModel(
                    invoice_id=inv.invoice_id, odoo_id=inv.odoo_id, client_id=inv.client_id,
                    amount=amount_xof, amount_residual=residual_xof,
                    currency=inv.currency, due_date=inv.due_date,
                    status=inv.status.value, invoice_date=inv.invoice_date,
                    invoice_name=inv.invoice_name,
                ))
        await session.commit()
    logger.info("Webhook : %d factures mises à jour (montants en XOF)", len(records))


_XOF_RATES_CACHE: dict[str, float] = {}  # {"USD": 610.5, "EUR": 655.9, ...}


async def _get_xof_rates(odoo: OdooAdapter) -> dict[str, float]:
    """Récupère les taux inverse (1 devise = X XOF) depuis Odoo."""
    global _XOF_RATES_CACHE
    try:
        currencies = await odoo._call(
            "res.currency", "search_read",
            [[["active", "=", True]]],
            {"fields": ["name", "inverse_rate"]},
        )
        # inverse_rate = combien vaut 1 unité de devise en XOF (ex: USD → 585.14)
        rates = {c["name"]: float(c.get("inverse_rate") or 1.0) for c in currencies}
        _XOF_RATES_CACHE = rates
        return rates
    except Exception as e:
        logger.warning("Impossible de récupérer les taux de change : %s", e)
        return _XOF_RATES_CACHE or {}


def _to_xof(amount: float, currency: str, rates: dict[str, float]) -> float:
    """Convertit un montant en XOF via inverse_rate. XOF ou devise inconnue → retourne tel quel."""
    if not currency or currency == "XOF" or not rates:
        return amount
    inverse_rate = rates.get(currency)
    if not inverse_rate:
        return amount
    return amount * inverse_rate


async def _sync_sale_orders_by_ids(odoo: OdooAdapter, ids: list[int]):
    rates = await _get_xof_rates(odoo)
    try:
        records = await odoo._call(
            "sale.order", "search_read",
            [[["id", "in", ids]]],
            {"fields": ["id", "name", "partner_id", "amount_total",
                        "currency_id", "date_order", "state", "user_id", "dossier_id", "invoice_ids"]},
        )
    except RuntimeError as e:
        if "dossier_id" in str(e):
            records = await odoo._call(
                "sale.order", "search_read",
                [[["id", "in", ids]]],
                {"fields": ["id", "name", "partner_id", "amount_total",
                            "currency_id", "date_order", "state", "user_id", "invoice_ids"]},
            )
        else:
            raise
    lines_by_order = await odoo.get_order_lines_by_ids([r["id"] for r in records])
    async with AsyncSessionLocal() as session:
        for so in records:
            order_id = f"so_{so['id']}"
            partner = so.get("partner_id") or [None, ""]
            date_order = _parse_date(so.get("date_order"))
            salesperson = _get_odoo_name(so.get("user_id"))
            dossier = _get_odoo_name(so.get("dossier_id")) or None
            lines = lines_by_order.get(so["id"], [])
            invoice_ids = so.get("invoice_ids") or []
            currency = _get_odoo_name(so.get("currency_id"), "XOF")
            amount_xof = _to_xof(float(so.get("amount_total", 0)), currency, rates)
            existing = await session.get(SaleOrderModel, order_id)
            if existing:
                existing.state = so.get("state", "sale")
                existing.amount = amount_xof
                existing.name = so["name"]
                existing.salesperson_name = salesperson
                existing.dossier_id = dossier
                existing.order_lines = lines
                existing.invoice_ids = invoice_ids
                existing.synced_at = datetime.utcnow()
            else:
                session.add(SaleOrderModel(
                    order_id=order_id, odoo_id=so["id"],
                    client_id=str(partner[0]) if partner[0] else "",
                    client_name=_get_odoo_name(partner),
                    name=so["name"],
                    amount=amount_xof,
                    currency=currency,
                    date_order=date_order,
                    state=so.get("state", "sale"),
                    salesperson_name=salesperson,
                    dossier_id=dossier,
                    order_lines=lines,
                    invoice_ids=invoice_ids,
                ))
        await session.commit()
    logger.info("Webhook : %d bons de commande mis à jour", len(records))


async def _sync_purchase_orders_by_ids(odoo: OdooAdapter, ids: list[int]):
    rates = await _get_xof_rates(odoo)
    try:
        records = await odoo._call(
            "purchase.order", "search_read",
            [[["id", "in", ids]]],
            {"fields": ["id", "name", "partner_id", "amount_total", "currency_id",
                        "date_order", "state", "dossier_id"]},
        )
    except Exception as e:
        logger.warning("purchase.order webhook indisponible : %s", e)
        return
    async with AsyncSessionLocal() as session:
        for po in records:
            order_id = f"po_{po['id']}"
            partner = po.get("partner_id") or [None, ""]
            date_order = _parse_date(po.get("date_order"))
            currency = _get_odoo_name(po.get("currency_id"), "XOF")
            amount_xof = _to_xof(float(po.get("amount_total", 0)), currency, rates)
            dossier = _get_odoo_name(po.get("dossier_id")) or None
            existing = await session.get(PurchaseOrderModel, order_id)
            if existing:
                existing.state = po.get("state", "purchase")
                existing.amount = amount_xof
                existing.dossier_id = dossier
                existing.synced_at = datetime.utcnow()
            else:
                session.add(PurchaseOrderModel(
                    order_id=order_id, odoo_id=po["id"],
                    client_id=str(partner[0]) if partner[0] else "",
                    client_name=_get_odoo_name(partner),
                    name=po["name"],
                    amount=amount_xof,
                    currency=currency,
                    date_order=date_order,
                    state=po.get("state", "purchase"),
                    dossier_id=dossier,
                ))
        await session.commit()
    logger.info("Webhook : %d achats mis à jour (montants en XOF)", len(records))


async def _sync_suppliers_by_ids(odoo: OdooAdapter, ids: list[int]):
    """Fournisseurs (res.partner, supplier_rank > 0 parmi les ids donnés). Un id peut être
    un client pur (supplier_rank=0) — filtré ici, silencieusement absent du résultat."""
    try:
        records = await odoo._call(
            "res.partner", "search_read",
            [[["id", "in", ids], ["supplier_rank", ">", 0]]],
            {"fields": ["id", "name", "credit_limit", "use_partner_credit_limit",
                        "property_supplier_payment_term_id", "supplier_rank"]},
        )
    except Exception as e:
        logger.warning("res.partner (fournisseurs) webhook indisponible : %s", e)
        return
    if not records:
        return
    terms = await odoo._get_payment_terms_days()
    async with AsyncSessionLocal() as session:
        for r in records:
            supplier_id = str(r["id"])
            term = r.get("property_supplier_payment_term_id") or None
            term_id = term[0] if term else None
            term_name = term[1] if term else None
            term_days = terms.get(term_id) if term_id else None
            existing = await session.get(SupplierModel, supplier_id)
            if existing:
                existing.name = r["name"]
                # N'écrase JAMAIS une valeur déjà connue par un null Odoo : la plupart des
                # fournisseurs n'ont pas encore de ligne de crédit/délai configuré côté
                # Odoo — un null ici signifie "pas encore renseigné", pas "supprimé".
                if r.get("credit_limit"):
                    existing.credit_limit = r.get("credit_limit")
                if term_name:
                    existing.payment_term_name = term_name
                    existing.payment_term_days = term_days
                existing.use_partner_credit_limit = bool(r.get("use_partner_credit_limit")) or existing.use_partner_credit_limit
                existing.supplier_rank = r.get("supplier_rank", 0)
                existing.synced_at = datetime.utcnow()
            else:
                session.add(SupplierModel(
                    supplier_id=supplier_id, odoo_id=r["id"], name=r["name"],
                    credit_limit=r.get("credit_limit"),
                    use_partner_credit_limit=bool(r.get("use_partner_credit_limit")),
                    payment_term_name=term_name, payment_term_days=term_days,
                    supplier_rank=r.get("supplier_rank", 0),
                ))
        await session.commit()
    logger.info("Webhook : %d fournisseurs mis à jour", len(records))


async def _sync_supplier_invoices_by_ids(odoo: OdooAdapter, ids: list[int]):
    """Factures fournisseurs (account.move, move_type=in_invoice parmi les ids donnés)."""
    rates = await _get_xof_rates(odoo)
    try:
        records = await odoo._call(
            "account.move", "search_read",
            [[["id", "in", ids], ["move_type", "=", "in_invoice"]]],
            {"fields": ["id", "name", "partner_id", "amount_total", "amount_residual",
                        "currency_id", "invoice_date", "invoice_date_due", "payment_state"]},
        )
    except Exception as e:
        logger.warning("account.move (factures fournisseurs) webhook indisponible : %s", e)
        return
    if not records:
        return
    async with AsyncSessionLocal() as session:
        for r in records:
            invoice_id = f"si_{r['id']}"
            partner = r.get("partner_id") or [None, ""]
            currency = _get_odoo_name(r.get("currency_id"), "XOF")
            amount_xof = _to_xof(float(r.get("amount_total") or 0), currency, rates)
            residual_xof = _to_xof(float(r.get("amount_residual") or 0), currency, rates)
            invoice_date = _parse_date(r.get("invoice_date"))
            due_date = _parse_date(r.get("invoice_date_due"))
            existing = await session.get(SupplierInvoiceModel, invoice_id)
            if existing:
                existing.payment_state = r.get("payment_state", "not_paid")
                existing.amount = amount_xof
                existing.amount_residual = residual_xof
                existing.synced_at = datetime.utcnow()
            else:
                session.add(SupplierInvoiceModel(
                    invoice_id=invoice_id, odoo_id=r["id"],
                    supplier_id=str(partner[0]) if partner[0] else "",
                    supplier_name=_get_odoo_name(partner),
                    amount=amount_xof, amount_residual=residual_xof, currency=currency,
                    invoice_date=invoice_date, due_date=due_date,
                    payment_state=r.get("payment_state", "not_paid"),
                ))
        await session.commit()
    logger.info("Webhook : %d factures fournisseurs mises à jour", len(records))


_DOSSIER_FIELDS = [
    "id", "name", "project_name", "state",
    "date_creation", "date_end_project",
    "partner_id", "saler_id",
    "amount_business_provisoire", "amount_ca_definitive",
    "depense_definitive", "depense_provisoire",
    "marge_definitive", "marge_provisoire", "marge_previsionnelle",
    "perc_marge_definitive", "perc_marge_provisoire", "perc_marge_previsionnelle",
    "amount_received", "amount_to_cash", "backlog",
    "amount_po_paid", "amount_po_to_cash",
    "sale_count", "invoice_count", "pinvoice_count", "purchase_count",
]


async def _sync_dossiers(odoo: OdooAdapter, since: datetime | None = None):
    """Synchronise neurones.dossier.manager → table dossiers SQLite."""
    domain = []
    if since:
        domain = [["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")]]

    # Compter et paginer par tranches de 500
    total = await odoo._call("neurones.dossier.manager", "search_count", [domain], {})
    logger.info("Dossiers à syncer : %d", total)

    new_d = updated_d = 0
    sync_at = datetime.utcnow()

    for offset in range(0, total, 500):
        records = await odoo._call(
            "neurones.dossier.manager", "search_read",
            [domain],
            {"fields": _DOSSIER_FIELDS, "limit": 500, "offset": offset, "order": "id asc"},
        )
        async with AsyncSessionLocal() as session:
            for d in records:
                ref = d["name"]
                client = (d.get("partner_id") or [None, ""])[1] or ""
                salesperson = (d.get("saler_id") or [None, ""])[1] or ""
                date_c_raw = d.get("date_creation") or ""
                date_e_raw = d.get("date_end_project") or ""
                date_creation = datetime.strptime(date_c_raw[:10], "%Y-%m-%d") if date_c_raw else None
                date_end = datetime.strptime(date_e_raw[:10], "%Y-%m-%d") if date_e_raw else None

                row = {
                    "odoo_id": d["id"],
                    "client_name": client,
                    "project_name": d.get("project_name") or None,
                    "salesperson": salesperson,
                    "state": d.get("state", "draft"),
                    "date_creation": date_creation,
                    "date_end_project": date_end,
                    "ca_provisoire": float(d.get("amount_business_provisoire") or 0),
                    "ca_definitif": float(d.get("amount_ca_definitive") or 0),
                    "depense_provisoire": float(d.get("depense_provisoire") or 0),
                    "depense_definitive": float(d.get("depense_definitive") or 0),
                    "marge_previsionnelle": float(d.get("marge_previsionnelle") or 0),
                    "marge_provisoire": float(d.get("marge_provisoire") or 0),
                    "marge_definitive": float(d.get("marge_definitive") or 0),
                    "perc_marge_previsionnelle": float(d.get("perc_marge_previsionnelle") or 0),
                    "perc_marge_provisoire": float(d.get("perc_marge_provisoire") or 0),
                    "perc_marge_definitive": float(d.get("perc_marge_definitive") or 0),
                    "montant_recu": float(d.get("amount_received") or 0),
                    "reste_a_encaisser": float(d.get("amount_to_cash") or 0),
                    "backlog": float(d.get("backlog") or 0),
                    "fournisseurs_payes": float(d.get("amount_po_paid") or 0),
                    "fournisseurs_restant": float(d.get("amount_po_to_cash") or 0),
                    "nb_bdc": int(d.get("sale_count") or 0),
                    "nb_factures_client": int(d.get("invoice_count") or 0),
                    "nb_factures_fournisseur": int(d.get("pinvoice_count") or 0),
                    "nb_achats": int(d.get("purchase_count") or 0),
                    "synced_at": sync_at,
                }
                existing = await session.get(DossierModel, ref)
                if existing:
                    for k, v in row.items():
                        setattr(existing, k, v)
                    updated_d += 1
                else:
                    session.add(DossierModel(dossier_ref=ref, **row))
                    new_d += 1
            await session.commit()

    logger.info("Dossiers synced : %d nouveaux, %d mis à jour", new_d, updated_d)


async def run_odoo_sync(force_full: bool = False):
    """
    ETL incrémental : synchronise uniquement les enregistrements modifiés depuis la dernière sync.
    Si force_full=True ou si c'est la première sync, récupère tout.
    """
    since = None if force_full else _load_last_sync()
    sync_start = datetime.utcnow()
    mode = "complète" if since is None else f"incrémentale (depuis {since.strftime('%H:%M:%S')})"
    logger.info("Démarrage sync Odoo → SQLite [%s]", mode)

    odoo = OdooAdapter()
    try:
        # ─── Taux de change (utilisés par factures, BDC et achats) ──────────
        rates = await _get_xof_rates(odoo)

        # ─── 1. Clients ──────────────────────────────────────────────────────
        clients = await odoo.get_all_clients(limit=5000, since=since)
        async with AsyncSessionLocal() as session:
            for c in clients:
                existing = await session.get(ClientModel, c.client_id)
                if existing:
                    existing.name = c.name
                    existing.sector = c.sector
                    existing.contact_email = c.contact_email
                    existing.phone = getattr(c, "phone", None)
                    existing.city = getattr(c, "city", None)
                    existing.country = getattr(c, "country", None)
                    existing.synced_at = sync_start
                else:
                    session.add(ClientModel(
                        client_id=c.client_id, odoo_id=c.odoo_id, name=c.name,
                        sector=c.sector, contact_email=c.contact_email,
                        phone=getattr(c, "phone", None),
                        city=getattr(c, "city", None),
                        country=getattr(c, "country", None),
                    ))
            await session.commit()

        # ─── 2. Factures (montants convertis en XOF) ─────────────────────────
        invoices = await odoo.get_all_invoices(limit=5000, since=since)
        async with AsyncSessionLocal() as session:
            new_inv = 0
            for inv in invoices:
                amount_xof = _to_xof(inv.amount, inv.currency, rates)
                residual_xof = _to_xof(inv.amount_residual, inv.currency, rates)
                existing = await session.get(InvoiceModel, inv.invoice_id)
                if existing:
                    existing.status = inv.status.value
                    existing.amount = amount_xof
                    existing.amount_residual = residual_xof
                    existing.synced_at = sync_start
                    if inv.invoice_date and not existing.invoice_date:
                        existing.invoice_date = inv.invoice_date
                    if inv.invoice_name and not existing.invoice_name:
                        existing.invoice_name = inv.invoice_name
                else:
                    session.add(InvoiceModel(
                        invoice_id=inv.invoice_id, odoo_id=inv.odoo_id, client_id=inv.client_id,
                        amount=amount_xof, currency=inv.currency, due_date=inv.due_date,
                        status=inv.status.value, invoice_date=inv.invoice_date,
                        invoice_name=inv.invoice_name,
                        amount_residual=residual_xof,
                    ))
                    new_inv += 1
            await session.commit()

        # ─── 2b. Dates de paiement réelles (account.payment) ─────────────────
        try:
            payment_dates = await odoo.get_payment_dates(since=since)
            if payment_dates:
                async with AsyncSessionLocal() as session:
                    updated_pay = 0
                    for odoo_id_str, pay_date in payment_dates.items():
                        result = await session.execute(
                            select(InvoiceModel).where(InvoiceModel.odoo_id == int(odoo_id_str))
                        )
                        inv_row = result.scalar_one_or_none()
                        if inv_row and inv_row.payment_date != pay_date:
                            inv_row.payment_date = pay_date
                            updated_pay += 1
                    await session.commit()
                    logger.info("Dates de paiement mises à jour : %d factures", updated_pay)
        except Exception as e:
            logger.warning("Sync dates de paiement échouée (non bloquant) : %s", e)

        # ─── 3. Bons de commande ─────────────────────────────────────────────
        sale_orders = await odoo.get_sale_orders(limit=5000, since=since)
        # Lignes d'articles en batch (par tranches de 500 pour éviter timeout Odoo)
        all_odoo_ids = [so["id"] for so in sale_orders]
        lines_by_order: dict[int, list] = {}
        for i in range(0, len(all_odoo_ids), 500):
            batch = await odoo.get_order_lines_by_ids(all_odoo_ids[i:i + 500])
            lines_by_order.update(batch)
        async with AsyncSessionLocal() as session:
            new_so = 0
            for so in sale_orders:
                partner = so.get("partner_id") or [None, ""]
                order_id = f"so_{so['id']}"
                date_order = _parse_date(so.get("date_order"))
                salesperson = _get_odoo_name(so.get("user_id"))
                dossier = _get_odoo_name(so.get("dossier_id")) or None
                lines = lines_by_order.get(so["id"], [])
                invoice_ids = so.get("invoice_ids") or []
                currency = _get_odoo_name(so.get("currency_id"), "XOF")
                amount_xof = _to_xof(float(so.get("amount_total", 0)), currency, rates)
                try:
                    existing = await session.get(SaleOrderModel, order_id)
                except json.JSONDecodeError as e:
                    # order_lines corrompu en base (donnée historique non-JSON) : on répare
                    # la ligne au lieu de laisser planter toute la sync.
                    logger.warning(
                        "order_lines corrompu pour %s, réparation automatique (reset) : %s",
                        order_id, e,
                    )
                    await session.execute(
                        text("UPDATE sale_orders SET order_lines = '[]' WHERE order_id = :oid"),
                        {"oid": order_id},
                    )
                    existing = await session.get(SaleOrderModel, order_id)
                if existing:
                    existing.state = so.get("state", "sale")
                    existing.amount = amount_xof
                    existing.name = so["name"]
                    existing.date_order = date_order
                    existing.salesperson_name = salesperson
                    existing.dossier_id = dossier
                    existing.order_lines = lines
                    existing.invoice_ids = invoice_ids
                    existing.synced_at = sync_start
                else:
                    session.add(SaleOrderModel(
                        order_id=order_id, odoo_id=so["id"],
                        client_id=str(partner[0]) if partner[0] else "",
                        client_name=_get_odoo_name(partner),
                        name=so["name"],
                        amount=amount_xof,
                        currency=currency,
                        date_order=date_order,
                        state=so.get("state", "sale"),
                        salesperson_name=salesperson,
                        dossier_id=dossier,
                        order_lines=lines,
                        invoice_ids=invoice_ids,
                    ))
                    new_so += 1
            await session.commit()

        # ─── 4. Achats (montants convertis en XOF) ───────────────────────────
        purchase_orders = await odoo.get_all_purchase_orders(limit=2000, since=since)
        async with AsyncSessionLocal() as session:
            new_po = 0
            for po in purchase_orders:
                partner = po.get("partner_id") or [None, ""]
                order_id = f"po_{po['id']}"
                date_order = _parse_date(po.get("date_order"))
                currency = _get_odoo_name(po.get("currency_id"), "XOF")
                amount_xof = _to_xof(float(po.get("amount_total", 0)), currency, rates)
                dossier = _get_odoo_name(po.get("dossier_id")) or None
                existing = await session.get(PurchaseOrderModel, order_id)
                if existing:
                    existing.state = po.get("state", "purchase")
                    existing.amount = amount_xof
                    existing.dossier_id = dossier
                    existing.synced_at = sync_start
                else:
                    session.add(PurchaseOrderModel(
                        order_id=order_id, odoo_id=po["id"],
                        client_id=str(partner[0]) if partner[0] else "",
                        client_name=_get_odoo_name(partner),
                        name=po["name"],
                        amount=amount_xof,
                        currency=currency,
                        date_order=date_order,
                        state=po.get("state", "purchase"),
                        dossier_id=dossier,
                    ))
                    new_po += 1
            await session.commit()

        # ─── 4b. Fournisseurs (crédit, délai de paiement négocié) ────────────
        suppliers = await odoo.get_all_suppliers(limit=5000, since=since)
        async with AsyncSessionLocal() as session:
            new_sup = 0
            for s in suppliers:
                supplier_id = str(s["id"])
                existing = await session.get(SupplierModel, supplier_id)
                if existing:
                    existing.name = s["name"]
                    # N'écrase jamais une valeur déjà connue par un null Odoo (cf. commentaire
                    # sur _sync_suppliers_by_ids) : la plupart des fournisseurs n'ont pas encore
                    # de ligne de crédit/délai configuré côté Odoo.
                    if s.get("credit_limit"):
                        existing.credit_limit = s.get("credit_limit")
                    if s.get("payment_term_name"):
                        existing.payment_term_name = s.get("payment_term_name")
                        existing.payment_term_days = s.get("payment_term_days")
                    existing.use_partner_credit_limit = bool(s.get("use_partner_credit_limit")) or existing.use_partner_credit_limit
                    existing.supplier_rank = s.get("supplier_rank", 0)
                    existing.synced_at = sync_start
                else:
                    session.add(SupplierModel(
                        supplier_id=supplier_id, odoo_id=s["id"], name=s["name"],
                        credit_limit=s.get("credit_limit"),
                        use_partner_credit_limit=bool(s.get("use_partner_credit_limit")),
                        payment_term_name=s.get("payment_term_name"),
                        payment_term_days=s.get("payment_term_days"),
                        supplier_rank=s.get("supplier_rank", 0),
                    ))
                    new_sup += 1
            await session.commit()

        # ─── 4c. Factures fournisseurs (échéances réelles pour le cash prévisionnel) ──
        supplier_invoices = await odoo.get_all_supplier_invoices(limit=5000, since=since)
        async with AsyncSessionLocal() as session:
            new_si = 0
            for r in supplier_invoices:
                invoice_id = f"si_{r['id']}"
                partner = r.get("partner_id") or [None, ""]
                currency = _get_odoo_name(r.get("currency_id"), "XOF")
                amount_xof = _to_xof(float(r.get("amount_total") or 0), currency, rates)
                residual_xof = _to_xof(float(r.get("amount_residual") or 0), currency, rates)
                invoice_date = _parse_date(r.get("invoice_date"))
                due_date = _parse_date(r.get("invoice_date_due"))
                existing = await session.get(SupplierInvoiceModel, invoice_id)
                if existing:
                    existing.payment_state = r.get("payment_state", "not_paid")
                    existing.amount = amount_xof
                    existing.amount_residual = residual_xof
                    existing.synced_at = sync_start
                else:
                    session.add(SupplierInvoiceModel(
                        invoice_id=invoice_id, odoo_id=r["id"],
                        supplier_id=str(partner[0]) if partner[0] else "",
                        supplier_name=_get_odoo_name(partner),
                        amount=amount_xof, amount_residual=residual_xof, currency=currency,
                        invoice_date=invoice_date, due_date=due_date,
                        payment_state=r.get("payment_state", "not_paid"),
                    ))
                    new_si += 1
            await session.commit()

        # ─── 4d. Dates de paiement réelles fournisseurs (account.payment) ────
        try:
            supplier_payment_dates = await odoo.get_supplier_payment_dates(since=since)
            if supplier_payment_dates:
                async with AsyncSessionLocal() as session:
                    updated_spay = 0
                    for odoo_id_str, pay_date in supplier_payment_dates.items():
                        result = await session.execute(
                            select(SupplierInvoiceModel).where(SupplierInvoiceModel.odoo_id == int(odoo_id_str))
                        )
                        si_row = result.scalar_one_or_none()
                        if si_row and si_row.payment_date != pay_date:
                            si_row.payment_date = pay_date
                            updated_spay += 1
                    await session.commit()
                    logger.info("Dates de paiement fournisseurs mises à jour : %d factures", updated_spay)
        except Exception as e:
            logger.warning("Sync dates de paiement fournisseurs échouée (non bloquant) : %s", e)

        # ─── 5. Projets (sync complète uniquement) ────────────────────────────
        if since is None:
            projects = await odoo.get_all_projects()
            async with AsyncSessionLocal() as session:
                for proj in projects:
                    existing = await session.get(ProjectModel, proj.project_id)
                    if not existing:
                        session.add(ProjectModel(
                            project_id=proj.project_id, odoo_id=proj.odoo_id,
                            client_id=proj.client_id, title=proj.title,
                            description=proj.description, start_date=proj.start_date,
                            end_date=proj.end_date, technologies=[], engineers=[],
                        ))
                await session.commit()

        # ─── 6. Dossiers commerciaux (neurones.dossier.manager) ─────────────
        try:
            await _sync_dossiers(odoo, since=since)
        except Exception as e:
            logger.warning("Sync dossiers échouée (non bloquant) : %s", e)

        # ─── 7. Pipeline commercial (crm.lead) — paginé ─────────────────────
        try:
            _opp_domain = [["type", "=", "opportunity"]]
            _opp_fields = ["id", "name", "partner_id", "expected_revenue", "probability",
                           "stage_id", "date_deadline", "user_id", "create_date", "order_ids"]
            total_opps = await odoo._call("crm.lead", "search_count", [_opp_domain], {})
            opportunities: list[dict] = []
            for offset in range(0, total_opps, 500):
                batch = await odoo._call(
                    "crm.lead", "search_read", [_opp_domain],
                    {"fields": _opp_fields, "limit": 500, "offset": offset, "order": "id asc"},
                )
                opportunities.extend(batch)
            async with AsyncSessionLocal() as session:
                new_opp = 0
                for opp in opportunities:
                    opp_id = f"opp_{opp['id']}"
                    partner = opp.get("partner_id") or [None, ""]
                    stage = _get_odoo_name(opp.get("stage_id"))
                    salesperson = _get_odoo_name(opp.get("user_id"))
                    deadline = _parse_date(opp.get("date_deadline"))
                    created_at = _parse_date(opp.get("create_date"))
                    order_ids = opp.get("order_ids") or []
                    existing = await session.get(OpportunityModel, opp_id)
                    if existing:
                        existing.name = opp.get("name", "")
                        existing.stage = stage
                        existing.expected_revenue = float(opp.get("expected_revenue", 0))
                        existing.probability = float(opp.get("probability", 0))
                        existing.salesperson_name = salesperson
                        existing.deadline = deadline
                        existing.order_ids = order_ids
                        existing.synced_at = sync_start
                    else:
                        session.add(OpportunityModel(
                            opp_id=opp_id,
                            odoo_id=opp["id"],
                            client_id=str(partner[0]) if partner[0] else None,
                            client_name=_get_odoo_name(partner),
                            name=opp.get("name", ""),
                            stage=stage,
                            expected_revenue=float(opp.get("expected_revenue", 0)),
                            probability=float(opp.get("probability", 0)),
                            salesperson_name=salesperson,
                            deadline=deadline,
                            created_at=created_at,
                            order_ids=order_ids,
                        ))
                        new_opp += 1
                await session.commit()
                logger.info("Pipeline commercial : %d opportunités synced (%d nouvelles)", len(opportunities), new_opp)
        except Exception as e:
            logger.warning("Sync pipeline commercial échouée (non bloquant) : %s", e)

        _save_last_sync(sync_start)

        elapsed = (datetime.utcnow() - sync_start).total_seconds()
        summary = {
            "mode": mode,
            "clients": len(clients),
            "invoices": len(invoices),
            "sale_orders": len(sale_orders),
            "purchase_orders": len(purchase_orders),
            "suppliers": len(suppliers),
            "supplier_invoices": len(supplier_invoices),
            "elapsed_seconds": round(elapsed, 2),
        }
        if clients or invoices or sale_orders or purchase_orders or suppliers or supplier_invoices:
            logger.info(
                "Sync terminée en %.1fs : %d clients, %d factures, %d BDC, %d achats, "
                "%d fournisseurs, %d factures fournisseurs",
                elapsed, len(clients), len(invoices), len(sale_orders), len(purchase_orders),
                len(suppliers), len(supplier_invoices),
            )
        else:
            logger.debug("Sync terminée en %.1fs : aucune modification détectée", elapsed)
        return summary

    except Exception as e:
        logger.error("Erreur sync Odoo : %s", e, exc_info=True)
        raise
    finally:
        await odoo.close()
