import logging
from datetime import datetime, timedelta
from typing import Optional
import httpx

from core.ports.crm_repository import CRMRepository
from core.domain.client import Client, Contract, Invoice, Project, ContractStatus, InvoiceStatus
from config.settings import settings

logger = logging.getLogger(__name__)


class OdooAdapter(CRMRepository):
    """
    Accès direct à Odoo 19 via JSON-RPC avec session persistante (cookie).
    Utilisé uniquement par OdooSyncJob pour alimenter le miroir SQLite local.
    Les use cases n'utilisent jamais cet adapter directement.
    """

    def __init__(self):
        self._url = settings.odoo_url
        self._db = settings.odoo_db
        self._username = settings.odoo_username
        self._password = settings.odoo_password
        self._uid: Optional[int] = None
        # Client persistant : les cookies de session sont conservés entre les appels
        self._client = httpx.AsyncClient(timeout=60, follow_redirects=True)

    async def _authenticate(self) -> int:
        if self._uid:
            return self._uid
        resp = await self._client.post(
            f"{self._url}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "id": 1,
                "params": {"db": self._db, "login": self._username, "password": self._password},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Odoo auth failed: {data['error']}")
        self._uid = data["result"]["uid"]
        logger.info("Odoo authentifié — uid=%d name=%s", self._uid, data["result"].get("name"))
        return self._uid

    async def _call(self, model: str, method: str, args: list, kwargs: dict = None) -> list:
        await self._authenticate()
        resp = await self._client.post(
            f"{self._url}/web/dataset/call_kw",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "id": 1,
                "params": {"model": model, "method": method, "args": args, "kwargs": kwargs or {}},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            msg = data["error"].get("data", {}).get("message", str(data["error"]))
            # Session expirée → on ré-authentifie une fois
            if "session" in msg.lower() or "expired" in msg.lower():
                logger.warning("Session Odoo expirée, ré-authentification...")
                self._uid = None
                return await self._call(model, method, args, kwargs)
            raise RuntimeError(f"Odoo RPC error [{model}.{method}]: {msg}")
        return data.get("result", [])

    async def _count(self, model: str, domain: list) -> int:
        result = await self._call(model, "search_count", [domain])
        return result if isinstance(result, int) else 0

    # ─── Clients ────────────────────────────────────────────────────────────

    async def get_client(self, name_or_id: str) -> Optional[Client]:
        domain = [["id", "=", int(name_or_id)]] if name_or_id.isdigit() else [["name", "ilike", name_or_id]]
        records = await self._call(
            "res.partner", "search_read", [domain],
            {"fields": ["id", "name", "email", "phone", "city", "country_id", "industry_id"], "limit": 1},
        )
        if not records:
            return None
        r = records[0]
        return self._partner_to_client(r)

    async def search_clients(self, query: str) -> list[Client]:
        records = await self._call(
            "res.partner", "search_read",
            [[["name", "ilike", query], ["is_company", "=", True]]],
            {"fields": ["id", "name", "email", "phone", "city"], "limit": 20, "order": "name asc"},
        )
        return [self._partner_to_client(r) for r in records]

    async def get_all_clients(self, limit: int = 2000, since: datetime | None = None) -> list[Client]:
        domain = [["is_company", "=", True], ["customer_rank", ">", 0]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")])
        records = await self._call(
            "res.partner", "search_read", [domain],
            {"fields": ["id", "name", "email", "phone", "city", "country_id", "industry_id"],
             "limit": limit, "order": "name asc"},
        )
        return [self._partner_to_client(r) for r in records]

    @staticmethod
    def _partner_to_client(r: dict) -> Client:
        industry = r.get("industry_id") or [None, None]
        country_field = r.get("country_id") or [None, None]
        return Client(
            client_id=str(r["id"]),
            name=r["name"],
            sector=industry[1] if len(industry) > 1 else None,
            odoo_id=r["id"],
            contact_email=r.get("email") or None,
            phone=r.get("phone") or None,
            city=r.get("city") or None,
            country=country_field[1] if len(country_field) > 1 else None,
        )

    # ─── Contrats / Comptes analytiques ─────────────────────────────────────

    async def get_contracts(self, client_id: str) -> list[Contract]:
        records = await self._call(
            "account.analytic.account", "search_read",
            [[["partner_id", "=", int(client_id)]]],
            {"fields": ["id", "name", "partner_id", "code", "plan_id"]},
        )
        return [self._analytic_to_contract(r, client_id) for r in records]

    async def get_expiring_contracts(self, days_threshold: int = 60) -> list[Contract]:
        # Sans module subscription, on retourne les BDC confirmés récents comme proxy
        threshold = (datetime.utcnow() + timedelta(days=days_threshold)).strftime("%Y-%m-%d")
        records = await self._call(
            "sale.order", "search_read",
            [[["state", "in", ["sale", "done"]], ["validity_date", "<=", threshold], ["validity_date", "!=", False]]],
            {"fields": ["id", "name", "partner_id", "amount_total", "currency_id", "date_order", "validity_date", "state"],
             "limit": 100, "order": "validity_date asc"},
        )
        return [self._sale_to_contract(r) for r in records]

    @staticmethod
    def _analytic_to_contract(r: dict, client_id: str) -> Contract:
        return Contract(
            contract_id=str(r["id"]),
            client_id=client_id,
            title=r["name"],
            value=0.0,
            currency="XOF",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2025, 12, 31),
            status=ContractStatus.ACTIVE,
            odoo_id=r["id"],
        )

    @staticmethod
    def _sale_to_contract(r: dict) -> Contract:
        partner = (r.get("partner_id") or [None, "?"])
        validity = r.get("validity_date", "2025-12-31") or "2025-12-31"
        return Contract(
            contract_id=f"sale_{r['id']}",
            client_id=str(partner[0]) if partner[0] else "",
            title=r["name"],
            value=float(r.get("amount_total", 0)),
            currency=(r.get("currency_id") or [None, "XOF"])[1],
            start_date=datetime.strptime(r.get("date_order", "2024-01-01")[:10], "%Y-%m-%d"),
            end_date=datetime.strptime(validity[:10], "%Y-%m-%d"),
            status=ContractStatus.EXPIRING_SOON,
            odoo_id=r["id"],
        )

    # ─── Factures ────────────────────────────────────────────────────────────

    async def get_invoices(self, client_id: str) -> list[Invoice]:
        records = await self._call(
            "account.move", "search_read",
            [[["partner_id", "=", int(client_id)], ["move_type", "=", "out_invoice"], ["state", "=", "posted"]]],
            {"fields": ["id", "name", "amount_total", "currency_id", "invoice_date", "invoice_date_due", "payment_state"],
             "limit": 50, "order": "invoice_date desc"},
        )
        return [self._move_to_invoice(r, client_id) for r in records]

    async def get_all_invoices(self, limit: int = 5000, since: datetime | None = None) -> list[Invoice]:
        domain = [["move_type", "=", "out_invoice"], ["state", "=", "posted"]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")])
        records = await self._call(
            "account.move", "search_read", [domain],
            {"fields": ["id", "name", "partner_id", "amount_total", "amount_residual",
                        "currency_id", "invoice_date", "invoice_date_due", "payment_state"],
             "limit": limit, "order": "invoice_date desc"},
        )
        return [self._move_to_invoice(r, str((r.get("partner_id") or [0])[0])) for r in records]

    @staticmethod
    def _move_to_invoice(r: dict, client_id: str) -> Invoice:
        status_map = {
            "paid": InvoiceStatus.PAID,
            "in_payment": InvoiceStatus.PENDING,
            "not_paid": InvoiceStatus.PENDING,
            "partial": InvoiceStatus.PENDING,
            "reversed": InvoiceStatus.CANCELLED,
        }
        due = r.get("invoice_date_due") or r.get("invoice_date") or "2025-12-31"
        inv_date_raw = r.get("invoice_date")
        inv_date = datetime.strptime(str(inv_date_raw)[:10], "%Y-%m-%d") if inv_date_raw else None
        return Invoice(
            invoice_id=str(r["id"]),
            client_id=client_id,
            amount=float(r.get("amount_total", 0)),
            currency=(r.get("currency_id") or [None, "XOF"])[1],
            due_date=datetime.strptime(str(due)[:10], "%Y-%m-%d"),
            status=status_map.get(r.get("payment_state", "not_paid"), InvoiceStatus.PENDING),
            odoo_id=r["id"],
            invoice_date=inv_date,
            invoice_name=r.get("name") or None,
            amount_residual=float(r.get("amount_residual") or 0),
        )

    # ─── Projets ─────────────────────────────────────────────────────────────

    async def get_projects(self, client_id: str) -> list[Project]:
        records = await self._call(
            "project.project", "search_read",
            [[["partner_id", "=", int(client_id)]]],
            {"fields": ["id", "name", "description", "date_start", "date", "user_id"]},
        )
        return [self._project_to_domain(r, client_id) for r in records]

    async def get_all_projects(self) -> list[Project]:
        records = await self._call(
            "project.project", "search_read", [[]],
            {"fields": ["id", "name", "partner_id", "description", "date_start", "date", "user_id"],
             "limit": 500, "order": "name asc"},
        )
        return [self._project_to_domain(r, str((r.get("partner_id") or [0])[0])) for r in records]

    @staticmethod
    def _project_to_domain(r: dict, client_id: str) -> Project:
        start = r.get("date_start", "2024-01-01") or "2024-01-01"
        end = r.get("date")
        return Project(
            project_id=str(r["id"]),
            client_id=client_id,
            title=r["name"],
            description=r.get("description") or "",
            start_date=datetime.strptime(str(start)[:10], "%Y-%m-%d"),
            end_date=datetime.strptime(str(end)[:10], "%Y-%m-%d") if end else None,
            odoo_id=r["id"],
        )

    # ─── Opportunités CRM ────────────────────────────────────────────────────

    async def get_opportunities(self, limit: int = 200) -> list[dict]:
        records = await self._call(
            "crm.lead", "search_read",
            [[["type", "=", "opportunity"]]],
            {"fields": ["id", "name", "partner_id", "expected_revenue", "probability",
                        "stage_id", "date_deadline", "user_id", "create_date"],
             "limit": limit, "order": "create_date desc"},
        )
        return records

    # ─── Bons de commande ────────────────────────────────────────────────────

    async def get_year_stats(self, year: int) -> dict:
        return {"year": year, "clients_with_orders": 0, "orders_count": 0, "revenue_xof": 0.0}

    async def get_ytd_stats(self, year: int, as_of=None, exclude_internal: bool = False) -> dict:
        return {"year": year, "as_of": None, "clients_with_orders": 0, "orders_count": 0, "revenue_xof": 0.0}

    async def get_account_rhythm_breaks(self, **kwargs) -> dict:
        return {
            "as_of": None, "nb_comptes_analyses": 0, "nb_comptes_rompus": 0,
            "ca_annuel_historique_xof": 0.0, "ca_ytd_xof": 0.0, "impaye_cumule_xof": 0.0,
            "comptes": [], "nb_comptes_dormants": 0, "ca_annuel_historique_dormants_xof": 0.0,
            "dormants": [], "note": "",
        }

    async def get_month_stats(self, year: int, month: int) -> dict:
        return {"year": year, "month": month, "clients_with_orders": 0, "orders_count": 0, "revenue_xof": 0.0}

    async def get_order_by_ref(self, ref: str) -> dict | None:
        try:
            records = await self._call(
                "sale.order", "search_read",
                [[["name", "=", ref]]],
                {"fields": ["id", "name", "partner_id", "amount_total", "currency_id",
                            "date_order", "state", "user_id", "dossier_id", "invoice_ids"], "limit": 1},
            )
        except RuntimeError as e:
            if "dossier_id" in str(e):
                records = await self._call(
                    "sale.order", "search_read",
                    [[["name", "=", ref]]],
                    {"fields": ["id", "name", "partner_id", "amount_total", "currency_id",
                                "date_order", "state", "user_id", "invoice_ids"], "limit": 1},
                )
            else:
                raise
        if not records:
            return None
        r = records[0]
        lines = await self.get_order_lines_by_ids([r["id"]])
        invoices = await self._get_invoices_by_ids(r.get("invoice_ids") or [])
        return {
            "name": r["name"],
            "client_name": (r.get("partner_id") or [None, "—"])[1],
            "amount": float(r.get("amount_total", 0)),
            "currency": (r.get("currency_id") or [None, "XOF"])[1],
            "date_order": r.get("date_order", "")[:10],
            "state": r.get("state", ""),
            "salesperson": (r.get("user_id") or [None, ""])[1] or "",
            "dossier": (r.get("dossier_id") or [None, ""])[1] or "",
            "lines": lines.get(r["id"], []),
            "invoices": invoices,
        }

    async def _get_invoices_by_ids(self, invoice_ids: list[int]) -> list[dict]:
        """Détail minimal des factures (account.move) liées à un bon de commande."""
        if not invoice_ids:
            return []
        try:
            records = await self._call(
                "account.move", "read", [invoice_ids],
                {"fields": ["name", "amount_total", "payment_state", "invoice_date"]},
            )
        except Exception as e:
            logger.warning("Impossible de récupérer les factures liées (%s) : %s", invoice_ids, e)
            return []
        return [
            {
                "name": inv.get("name") or "",
                "amount": float(inv.get("amount_total", 0)),
                "status": inv.get("payment_state") or "",
                "date": (inv.get("invoice_date") or "")[:10],
            }
            for inv in records
        ]

    async def get_payment_dates(self, since: datetime | None = None) -> dict[str, datetime]:
        """
        Retourne {invoice_odoo_id (str): payment_date} pour toutes les factures payées.
        Utilise invoice_payments_widget sur account.move (les paiements clients dans Odoo
        ne passent pas par account.payment mais par des écritures journal directes).
        """
        domain: list = [["move_type", "=", "out_invoice"], ["payment_state", "in", ["paid", "in_payment", "partial"]]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d")])
        try:
            invoices = await self._call(
                "account.move", "search_read", [domain],
                {"fields": ["id", "invoice_payments_widget"], "limit": 10000},
            )
        except Exception as e:
            logger.warning("Impossible de récupérer invoice_payments_widget : %s", e)
            return {}

        result: dict[str, datetime] = {}
        for inv in invoices:
            widget = inv.get("invoice_payments_widget")
            if not widget:
                continue
            # widget peut être un dict ou False
            if isinstance(widget, bool):
                continue
            content = widget.get("content") if isinstance(widget, dict) else []
            for entry in (content or []):
                date_raw = entry.get("date")
                if not date_raw:
                    continue
                try:
                    pay_date = datetime.strptime(str(date_raw)[:10], "%Y-%m-%d")
                except ValueError:
                    continue
                inv_key = str(inv["id"])
                # Garder la date de paiement la plus récente
                if inv_key not in result or pay_date > result[inv_key]:
                    result[inv_key] = pay_date

        logger.info("Dates de paiement récupérées : %d factures payées", len(result))
        return result

    async def get_supplier_payment_dates(self, since: datetime | None = None) -> dict[str, datetime]:
        """Symétrique de get_payment_dates côté FOURNISSEURS (in_invoice) — même mécanisme
        invoice_payments_widget. Nécessaire pour comparer le délai de paiement RÉEL au
        délai négocié (SupplierModel.payment_term_days), pas juste constater qu'une
        facture est actuellement en retard."""
        domain: list = [["move_type", "=", "in_invoice"], ["payment_state", "in", ["paid", "in_payment", "partial"]]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d")])
        try:
            invoices = await self._call(
                "account.move", "search_read", [domain],
                {"fields": ["id", "invoice_payments_widget"], "limit": 10000},
            )
        except Exception as e:
            logger.warning("Impossible de récupérer invoice_payments_widget (fournisseurs) : %s", e)
            return {}

        result: dict[str, datetime] = {}
        for inv in invoices:
            widget = inv.get("invoice_payments_widget")
            if not widget or isinstance(widget, bool):
                continue
            content = widget.get("content") if isinstance(widget, dict) else []
            for entry in (content or []):
                date_raw = entry.get("date")
                if not date_raw:
                    continue
                try:
                    pay_date = datetime.strptime(str(date_raw)[:10], "%Y-%m-%d")
                except ValueError:
                    continue
                inv_key = str(inv["id"])
                if inv_key not in result or pay_date > result[inv_key]:
                    result[inv_key] = pay_date

        logger.info("Dates de paiement fournisseurs récupérées : %d factures payées", len(result))
        return result

    async def get_order_lines_by_ids(self, order_ids: list[int]) -> dict[int, list]:
        """Retourne {odoo_order_id: [{product, product_code, product_category, qty, subtotal, unit_price}]}."""
        if not order_ids:
            return {}
        # Tente d'abord avec price_unit (disponible en standard Odoo)
        try:
            lines = await self._call(
                "sale.order.line", "search_read",
                [[["order_id", "in", order_ids]]],
                {"fields": ["order_id", "product_id", "name", "product_uom_qty",
                            "price_subtotal", "price_unit"],
                 "limit": 10000},
            )
        except Exception:
            # Fallback minimal sans price_unit
            try:
                lines = await self._call(
                    "sale.order.line", "search_read",
                    [[["order_id", "in", order_ids]]],
                    {"fields": ["order_id", "product_id", "name", "product_uom_qty", "price_subtotal"],
                     "limit": 10000},
                )
            except Exception as e:
                logger.warning("Impossible de récupérer les lignes de commande : %s", e)
                return {}

        # Référence article (default_code) + catégorie, en un seul appel batché sur
        # les produits distincts — pour retrouver le catalogue réel (cross-sell, GED…).
        product_ids = sorted({
            (line.get("product_id") or [None])[0]
            for line in lines if line.get("product_id")
        })
        product_meta: dict[int, dict] = {}
        if product_ids:
            try:
                products = await self._call(
                    "product.product", "read", [product_ids],
                    {"fields": ["default_code", "categ_id"]},
                )
                product_meta = {
                    p["id"]: {
                        "code": p.get("default_code") or None,
                        "category": (p.get("categ_id") or [None, None])[1],
                    }
                    for p in products
                }
            except Exception as e:
                logger.warning("Impossible de récupérer référence/catégorie produit : %s", e)

        result: dict[int, list] = {}
        for line in lines:
            oid = (line.get("order_id") or [None])[0]
            if not oid:
                continue
            pid = (line.get("product_id") or [None])[0]
            product_name = (line.get("product_id") or [None, ""])[1] or line.get("name", "")
            meta = product_meta.get(pid, {})
            qty = float(line.get("product_uom_qty", 0))
            subtotal = float(line.get("price_subtotal", 0))
            unit_price = float(line.get("price_unit", 0)) if "price_unit" in line else None
            result.setdefault(oid, []).append({
                "product": product_name,
                "product_code": meta.get("code"),
                "product_category": meta.get("category"),
                "qty": qty,
                "subtotal": subtotal,
                "unit_price": unit_price,
            })
        return result

    async def get_sale_orders(self, client_id: str = None, year: int | None = None, limit: int = 100, since: datetime | None = None) -> list[dict]:  # signature matches port
        domain = [["state", "in", ["sale", "done"]]]
        if client_id:
            domain.append(["partner_id", "=", int(client_id)])
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")])
        fields_with_dossier = ["id", "name", "partner_id", "amount_total",
                               "currency_id", "date_order", "state", "user_id", "dossier_id", "invoice_ids"]
        fields_without_dossier = ["id", "name", "partner_id", "amount_total",
                                  "currency_id", "date_order", "state", "user_id", "invoice_ids"]
        try:
            records = await self._call(
                "sale.order", "search_read", [domain],
                {"fields": fields_with_dossier, "limit": limit, "order": "date_order desc"},
            )
        except RuntimeError as e:
            if "dossier_id" in str(e):
                logger.warning("Champ dossier_id absent dans Odoo — sync sans ce champ : %s", e)
                records = await self._call(
                    "sale.order", "search_read", [domain],
                    {"fields": fields_without_dossier, "limit": limit, "order": "date_order desc"},
                )
            else:
                raise
        return records

    async def get_all_purchase_orders(self, limit: int = 2000, since: datetime | None = None) -> list[dict]:
        domain = [["state", "in", ["purchase", "done"]]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")])
        # dossier_id relie l'achat à la marge RÉELLE de la mission qu'il a servie (cf.
        # SupplierModel/get_supplier_intelligence) — même patron défensif que sale.order
        # ci-dessus : le champ existe en prod (vérifié via fields_get), mais on retombe
        # sans lui plutôt que de casser toute la synchro achats si jamais absent ailleurs.
        fields_with_dossier = ["id", "name", "partner_id", "amount_total", "currency_id",
                               "date_order", "state", "dossier_id"]
        fields_without_dossier = ["id", "name", "partner_id", "amount_total", "currency_id",
                                  "date_order", "state"]
        try:
            return await self._call(
                "purchase.order", "search_read", [domain],
                {"fields": fields_with_dossier, "limit": limit, "order": "date_order desc"},
            )
        except RuntimeError as e:
            if "dossier_id" in str(e):
                logger.warning("Champ dossier_id absent sur purchase.order — sync sans ce champ : %s", e)
                return await self._call(
                    "purchase.order", "search_read", [domain],
                    {"fields": fields_without_dossier, "limit": limit, "order": "date_order desc"},
                )
            logger.warning("purchase.order non disponible : %s", e)
            return []
        except Exception as e:
            logger.warning("purchase.order non disponible : %s", e)
            return []

    # ─── Fournisseurs (res.partner, supplier_rank > 0) ────────────────────────

    async def get_all_suppliers(self, limit: int = 2000, since: datetime | None = None) -> list[dict]:
        """Fournisseurs réels — plafond de crédit et délai de paiement négocié, jamais
        synchronisés avant ce soir (cf. SupplierModel). Distinct de get_all_clients qui
        filtre sur customer_rank : un partner peut être fournisseur sans être client."""
        domain = [["supplier_rank", ">", 0]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")])
        records = await self._call(
            "res.partner", "search_read", [domain],
            {"fields": ["id", "name", "credit_limit", "use_partner_credit_limit",
                        "property_supplier_payment_term_id", "supplier_rank"],
             "limit": limit, "order": "name asc"},
        )
        terms = await self._get_payment_terms_days()
        result = []
        for r in records:
            term = r.get("property_supplier_payment_term_id") or None
            term_id = term[0] if term else None
            term_name = term[1] if term else None
            result.append({
                "id": r["id"],
                "name": r["name"],
                "credit_limit": r.get("credit_limit"),
                "use_partner_credit_limit": bool(r.get("use_partner_credit_limit")),
                "payment_term_name": term_name,
                "payment_term_days": terms.get(term_id) if term_id else None,
                "supplier_rank": r.get("supplier_rank", 0),
            })
        return result

    _payment_terms_cache: dict[int, int] | None = None

    async def _get_payment_terms_days(self) -> dict[int, int]:
        """{payment_term_id: nb_days de la tranche la PLUS ÉLOIGNÉE} — le pire cas de
        règlement complet du terme négocié (ex: "30% à 30j, 70% à 60j" → 60), comparable
        à un retard réel constaté sur une facture. Mis en cache : référentiel stable,
        pas besoin de le relire à chaque synchro (contrairement aux montants/dates)."""
        if self._payment_terms_cache is not None:
            return self._payment_terms_cache
        try:
            lines = await self._call(
                "account.payment.term.line", "search_read", [[]],
                {"fields": ["payment_id", "nb_days"]},
            )
        except Exception as e:
            logger.warning("account.payment.term.line indisponible : %s", e)
            return {}
        days_by_term: dict[int, int] = {}
        for line in lines:
            payment = line.get("payment_id") or [None]
            term_id = payment[0]
            if term_id is None:
                continue
            days = int(line.get("nb_days") or 0)
            days_by_term[term_id] = max(days_by_term.get(term_id, 0), days)
        self._payment_terms_cache = days_by_term
        return days_by_term

    async def get_all_supplier_invoices(self, limit: int = 5000, since: datetime | None = None) -> list[dict]:
        """Factures FOURNISSEURS (in_invoice) — jamais synchronisées avant ce soir (seules
        les factures clients out_invoice l'étaient, cf. get_all_invoices). Nécessaires pour
        la ligne de crédit consommée et le cash prévisionnel fournisseurs (échéances réelles,
        pas des commandes d'achat qui n'ont pas de date de règlement)."""
        domain = [["move_type", "=", "in_invoice"], ["state", "=", "posted"]]
        if since:
            domain.append(["write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")])
        try:
            return await self._call(
                "account.move", "search_read", [domain],
                {"fields": ["id", "name", "partner_id", "amount_total", "amount_residual",
                            "currency_id", "invoice_date", "invoice_date_due", "payment_state"],
                 "limit": limit, "order": "invoice_date_due asc"},
            )
        except Exception as e:
            logger.warning("Factures fournisseurs (in_invoice) non disponibles : %s", e)
            return []

    # ─── Stats globales ──────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        total_clients = await self._count("res.partner", [["is_company", "=", True], ["customer_rank", ">", 0]])
        total_invoices = await self._count("account.move", [["move_type", "=", "out_invoice"], ["state", "=", "posted"]])
        paid_invoices  = await self._count("account.move", [["move_type", "=", "out_invoice"], ["state", "=", "posted"], ["payment_state", "=", "paid"]])
        total_orders   = await self._count("sale.order", [["state", "in", ["sale", "done"]]])
        total_opps     = await self._count("crm.lead", [["type", "=", "opportunity"]])
        return {
            "clients": total_clients,
            "invoices_total": total_invoices,
            "invoices_paid": total_invoices and paid_invoices,
            "sale_orders": total_orders,
            "opportunities": total_opps,
        }

    async def get_aggregate_stats(self) -> dict:
        stats = await self.get_stats()
        return {
            "clients": stats.get("clients", 0),
            "invoices": stats.get("invoices_total", 0),
            "invoices_paid": stats.get("invoices_paid", 0),
            "sale_orders": stats.get("sale_orders", 0),
            "total_revenue_xof": 0,
        }

    async def get_recent_orders(self, limit: int = 5, year: int | None = None) -> list[dict]:
        return []

    async def get_top_clients(self, limit: int = 5, year: int | None = None) -> list[dict]:
        return []

    async def get_clients_by_month(self, year: int, limit: int = 10) -> dict[int, list[dict]]:
        return {}

    async def get_unpaid_invoices(self, limit: int = 10) -> list[dict]:
        return []

    async def get_unpaid_exposure(self) -> dict:
        return {}

    async def get_dossier(self, ref: str) -> dict | None:
        return None

    async def get_dossiers_by_client(self, client_name: str, year: int | None = None) -> list[dict]:
        return []

    async def get_margin_stats(self, year: int | None = None) -> dict:
        return {}

    async def get_top_margin_dossiers(self, limit: int = 10, year: int | None = None,
                                      metric: str = "marge_provisoire") -> list[dict]:
        return []

    async def get_pipeline_stats(self) -> dict:
        return {}

    async def get_hot_leads(self, limit: int = 10) -> list[dict]:
        return []

    async def get_revenue_by_salesperson(self, year: int | None = None, quarter: int | None = None) -> list[dict]:
        return []

    async def score_client_risk(self, client_id: str | None = None, limit: int = 20) -> list[dict]:
        return []

    async def get_revenue_by_sector(self, year: int | None = None, limit: int = 20) -> list[dict]:
        return []

    async def get_quarterly_forecast(self, year: int | None = None) -> dict:
        return {}

    async def get_lost_deals(self, limit: int = 20) -> dict:
        return {}

    async def get_order_lines(self, limit: int = 20000) -> list[dict]:
        return []

    async def get_top_suppliers(self, limit: int = 20) -> list[dict]:
        return []

    async def get_supplier_intelligence(self, limit: int = 20) -> list[dict]:
        return []

    async def get_client_portfolio(self, limit: int = 50, clients: list[str] | None = None) -> list[dict]:
        return []

    async def get_cross_sell_opportunities(self, product_anchor: str, product_target: str | None = None, limit: int = 20) -> list[dict]:
        return []

    async def search_orders_by_product(self, product_query: str, year: int | None = None) -> list[dict]:
        return []

    async def get_revenue_by_product(self, year: int | None = None, limit: int = 30) -> list[dict]:
        return []

    async def get_client_retention(self, year: int | None = None) -> dict:
        return {}

    async def sync_from_odoo(self) -> dict:
        logger.info("Synchronisation Odoo → SQLite déclenchée via OdooSyncJob")
        return {}

    async def close(self):
        await self._client.aclose()
