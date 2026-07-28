import logging
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select, or_

from core.ports.crm_repository import CRMRepository
from core.domain.client import Client, Contract, Invoice, Project, ContractStatus, InvoiceStatus
from db.database import AsyncSessionLocal
from db.models import (
    ClientModel, ContractModel, InvoiceModel, ProjectModel, SaleOrderModel, DossierModel,
    SupplierModel,
)

logger = logging.getLogger(__name__)


class LocalCRMAdapter(CRMRepository):
    """
    Lit les données CRM depuis le miroir SQLite local — réponses <10ms.
    Alimenté toutes les 2h par OdooSyncJob.
    """

    async def get_client(self, name_or_id: str) -> Optional[Client]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClientModel).where(
                    or_(
                        ClientModel.client_id == name_or_id,
                        ClientModel.name.ilike(f"%{name_or_id}%"),
                    )
                ).limit(1)
            )
            row = result.scalar_one_or_none()
            return self._client_to_domain(row) if row else None

    async def search_clients(self, query: str) -> list[Client]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClientModel).where(ClientModel.name.ilike(f"%{query}%")).limit(10)
            )
            return [self._client_to_domain(r) for r in result.scalars()]

    async def get_contracts(self, client_id: str) -> list[Contract]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ContractModel).where(ContractModel.client_id == client_id)
            )
            return [self._contract_to_domain(r) for r in result.scalars()]

    async def get_expiring_contracts(self, days_threshold: int = 60) -> list[Contract]:
        threshold_date = datetime.utcnow() + timedelta(days=days_threshold)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ContractModel).where(
                    ContractModel.end_date <= threshold_date,
                    ContractModel.status == "active",
                )
            )
            return [self._contract_to_domain(r) for r in result.scalars()]

    async def get_invoices(self, client_id: str) -> list[Invoice]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(InvoiceModel).where(InvoiceModel.client_id == client_id)
            )
            return [self._invoice_to_domain(r) for r in result.scalars()]

    async def get_projects(self, client_id: str) -> list[Project]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.client_id == client_id)
            )
            return [self._project_to_domain(r) for r in result.scalars()]

    async def get_sale_orders(self, client_id: str, year: int | None = None) -> list[dict]:
        from sqlalchemy import extract
        async with AsyncSessionLocal() as session:
            q = (
                select(SaleOrderModel)
                .where(SaleOrderModel.client_id == client_id)
            )
            if year is not None:
                q = q.where(extract("year", SaleOrderModel.date_order) == year)
            q = q.order_by(SaleOrderModel.date_order.desc()).limit(50)
            result = await session.execute(q)
            return [
                {
                    "order_id": r.order_id,
                    "name": r.name,
                    "amount": r.amount,
                    "currency": r.currency,
                    "date_order": r.date_order.strftime("%d/%m/%Y") if r.date_order else "—",
                    "state": r.state,
                    "salesperson": r.salesperson_name or "",
                    "dossier": r.dossier_id or "",
                    "lines": r.order_lines or [],
                }
                for r in result.scalars()
            ]

    async def get_year_stats(self, year: int, exclude_internal: bool = False) -> dict:
        from sqlalchemy import func, extract
        async with AsyncSessionLocal() as session:
            year_filter = extract("year", SaleOrderModel.date_order) == year
            state_filter = SaleOrderModel.state.in_(["sale", "done"])
            filters = [year_filter, state_filter]
            if exclude_internal:
                # Récupère les client_ids des entités internes (NEURONES*)
                internal_ids_result = await session.execute(
                    select(ClientModel.client_id).where(ClientModel.name.ilike("%NEURONES%"))
                )
                internal_ids = [r[0] for r in internal_ids_result.all()]
                if internal_ids:
                    filters.append(~SaleOrderModel.client_id.in_(internal_ids))
            clients_with_orders = (await session.execute(
                select(func.count(func.distinct(SaleOrderModel.client_id))).where(*filters)
            )).scalar() or 0
            orders_count = (await session.execute(
                select(func.count()).select_from(SaleOrderModel).where(*filters)
            )).scalar() or 0
            revenue = (await session.execute(
                select(func.sum(SaleOrderModel.amount)).where(*filters)
            )).scalar() or 0
        return {
            "year": year,
            "clients_with_orders": clients_with_orders,
            "orders_count": orders_count,
            "revenue_xof": float(revenue),
        }

    async def get_month_stats(self, year: int, month: int) -> dict:
        from sqlalchemy import func, extract, and_
        async with AsyncSessionLocal() as session:
            period_filter = and_(
                extract("year", SaleOrderModel.date_order) == year,
                extract("month", SaleOrderModel.date_order) == month,
            )
            clients_with_orders = (await session.execute(
                select(func.count(func.distinct(SaleOrderModel.client_id))).where(period_filter)
            )).scalar() or 0
            orders_count = (await session.execute(
                select(func.count()).select_from(SaleOrderModel).where(period_filter)
            )).scalar() or 0
            revenue = (await session.execute(
                select(func.sum(SaleOrderModel.amount)).where(period_filter)
            )).scalar() or 0
        return {
            "year": year,
            "month": month,
            "clients_with_orders": int(clients_with_orders),
            "orders_count": int(orders_count),
            "revenue_xof": float(revenue),
        }

    async def get_order_by_ref(self, ref: str) -> dict | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SaleOrderModel, ClientModel)
                .join(ClientModel, SaleOrderModel.client_id == ClientModel.client_id, isouter=True)
                .where(SaleOrderModel.name == ref)
                .limit(1)
            )
            row = result.first()
            if not row:
                return None
            o, c = row

            invoices: list[dict] = []
            invoice_odoo_ids = o.invoice_ids or []
            if invoice_odoo_ids:
                inv_result = await session.execute(
                    select(InvoiceModel).where(InvoiceModel.odoo_id.in_(invoice_odoo_ids))
                )
                invoices = [
                    {
                        "name": inv.invoice_name or inv.invoice_id,
                        "amount": inv.amount,
                        "status": inv.status,
                        "date": inv.invoice_date.strftime("%d/%m/%Y") if inv.invoice_date else "—",
                    }
                    for inv in inv_result.scalars().all()
                ]

            return {
                "name": o.name,
                "client_name": c.name if c else "—",
                "client_email": c.contact_email if c else None,
                "client_phone": c.phone if c else None,
                "client_city": c.city if c else None,
                "amount": o.amount,
                "currency": o.currency,
                "date_order": o.date_order.strftime("%d/%m/%Y") if o.date_order else "—",
                "state": o.state,
                "salesperson": o.salesperson_name or "",
                "dossier": o.dossier_id or "",
                "lines": o.order_lines or [],
                "invoices": invoices,
            }

    async def get_aggregate_stats(self) -> dict:
        from sqlalchemy import func, select as sa_select
        from db.models import InvoiceModel
        async with AsyncSessionLocal() as session:
            clients_count = (await session.execute(sa_select(func.count()).select_from(ClientModel))).scalar()
            invoices_count = (await session.execute(sa_select(func.count()).select_from(InvoiceModel))).scalar()
            paid_count = (await session.execute(
                sa_select(func.count()).select_from(InvoiceModel).where(InvoiceModel.status == "paid")
            )).scalar()
            orders_count = (await session.execute(sa_select(func.count()).select_from(SaleOrderModel))).scalar()
            total_revenue = (await session.execute(sa_select(func.sum(SaleOrderModel.amount)))).scalar() or 0
        return {
            "clients": clients_count,
            "invoices": invoices_count,
            "invoices_paid": paid_count,
            "sale_orders": orders_count,
            "total_revenue_xof": total_revenue,
        }

    async def get_recent_orders(self, limit: int = 5, year: int | None = None) -> list[dict]:
        from sqlalchemy import extract
        async with AsyncSessionLocal() as session:
            q = (
                select(SaleOrderModel, ClientModel)
                .join(ClientModel, SaleOrderModel.client_id == ClientModel.client_id, isouter=True)
                .order_by(SaleOrderModel.date_order.desc())
            )
            if year is not None:
                q = q.where(extract("year", SaleOrderModel.date_order) == year)
            q = q.limit(limit)
            result = await session.execute(q)
            return [
                {
                    "ref": o.name,
                    "client": c.name if c else "—",
                    "montant_xof": o.amount,
                    "date": o.date_order.strftime("%d/%m/%Y") if o.date_order else "—",
                    "état": o.state,
                }
                for o, c in result.all()
            ]

    async def get_top_clients(self, limit: int = 5, year: int | None = None) -> list[dict]:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            base_sql = """
                SELECT o.client_id, o.client_name,
                       COUNT(o.order_id) as nb_commandes,
                       SUM(o.amount) as ca_total,
                       MAX(COALESCE(NULLIF(c.country, ''), 'Autres/non renseigné')) as pays
                FROM sale_orders o
                LEFT JOIN clients c ON o.client_id = c.client_id
                WHERE o.state IN ('sale', 'done')
            """
            params: dict = {}
            if year is not None:
                base_sql += " AND substr(o.date_order, 1, 4) = :year"
                params["year"] = str(year)
            base_sql += " GROUP BY o.client_id, o.client_name ORDER BY ca_total DESC LIMIT :limit"
            params["limit"] = limit
            result = await session.execute(text(base_sql), params)
            return [
                {
                    "client": row[1],
                    "nb_commandes": row[2] or 0,
                    "ca_total_xof": float(row[3] or 0),
                    "pays": row[4],
                }
                for row in result.fetchall()
            ]

    async def get_unpaid_invoices(self, limit: int = 10) -> list[dict]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(InvoiceModel, ClientModel)
                .join(ClientModel, InvoiceModel.client_id == ClientModel.client_id, isouter=True)
                .where(InvoiceModel.status != "paid")
                .order_by(InvoiceModel.amount.desc())
                .limit(limit)
            )
            return [
                {
                    "client": c.name if c else "—",
                    "montant_xof": inv.amount,
                    "échéance": inv.due_date.strftime("%d/%m/%Y") if inv.due_date else "—",
                    "statut": inv.status,
                }
                for inv, c in result.all()
            ]

    async def get_unpaid_exposure(self) -> dict:
        """Exposition totale aux impayés : résumé global + top débiteurs."""
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            # Total global
            r = await session.execute(text(
                "SELECT COUNT(*), SUM(amount) FROM invoices WHERE status != 'paid'"
            ))
            row = r.fetchone()
            total_nb, total_amount = row[0] or 0, float(row[1] or 0)

            # Par statut
            r2 = await session.execute(text(
                "SELECT status, COUNT(*), SUM(amount) FROM invoices "
                "WHERE status != 'paid' GROUP BY status"
            ))
            par_statut = {row[0]: {"nb": row[1], "montant": float(row[2] or 0)} for row in r2.fetchall()}

            # Retard > 90 jours
            r3 = await session.execute(text(
                "SELECT COUNT(*), SUM(amount) FROM invoices "
                "WHERE status != 'paid' AND due_date IS NOT NULL "
                "AND julianday('now') - julianday(due_date) > 90"
            ))
            row3 = r3.fetchone()
            retard_90j_nb, retard_90j_montant = row3[0] or 0, float(row3[1] or 0)

            # Top 10 débiteurs
            r4 = await session.execute(text(
                "SELECT c.name, COUNT(i.invoice_id), SUM(i.amount), "
                "MAX(CAST(julianday('now') - julianday(i.due_date) AS INTEGER)) "
                "FROM invoices i LEFT JOIN clients c ON i.client_id = c.client_id "
                "WHERE i.status != 'paid' "
                "GROUP BY i.client_id ORDER BY SUM(i.amount) DESC LIMIT 10"
            ))
            top_debiteurs = [
                {
                    "client": row[0] or "—",
                    "nb_factures": row[1],
                    "montant_total_xof": float(row[2] or 0),
                    "retard_max_jours": int(row[3] or 0),
                }
                for row in r4.fetchall()
            ]

        return {
            "exposition_totale_xof": total_amount,
            "nb_factures_impayees": total_nb,
            "par_statut": par_statut,
            "retard_90j_nb_factures": retard_90j_nb,
            "retard_90j_montant_xof": retard_90j_montant,
            "top_10_debiteurs": top_debiteurs,
        }

    async def get_invoice_collection_stats(self, client_name: str = "", year: int | None = None) -> dict:
        """
        Calcule les stats de recouvrement :
        - Délai moyen entre invoice_date et due_date (délai accordé)
        - Retard moyen sur les factures impayées en souffrance
        - % payé, montant total, montant en attente
        """

        async with AsyncSessionLocal() as session:
            q = (
                select(InvoiceModel, ClientModel.name.label("client_name"))
                .join(ClientModel, InvoiceModel.client_id == ClientModel.client_id, isouter=True)
            )
            if client_name:
                q = q.where(ClientModel.name.ilike(f"%{client_name}%"))
            if year:
                q = q.where(
                    InvoiceModel.invoice_date >= f"{year}-01-01",
                    InvoiceModel.invoice_date < f"{year+1}-01-01",
                )
            result = await session.execute(q)
            rows = result.all()

        if not rows:
            return {"error": f"Aucune facture trouvée pour {client_name or 'tous les clients'}" + (f" en {year}" if year else "")}

        today = datetime.utcnow().replace(tzinfo=None)
        total = len(rows)
        paid = sum(1 for inv, _ in rows if inv.status == "paid")
        pending = total - paid
        montant_total = sum(inv.amount for inv, _ in rows)
        montant_paye = sum(inv.amount for inv, _ in rows if inv.status == "paid")
        montant_en_attente = sum(inv.amount for inv, _ in rows if inv.status != "paid")

        # Délai réel de recouvrement = payment_date - invoice_date (factures payées uniquement)
        delais_reels = []
        for inv, _ in rows:
            if inv.status == "paid" and inv.payment_date and inv.invoice_date:
                d = (inv.payment_date.replace(tzinfo=None) - inv.invoice_date.replace(tzinfo=None)).days
                if 0 <= d <= 730:  # filtrer les aberrations
                    delais_reels.append(d)

        # Délai accordé = due_date - invoice_date (délai contractuel)
        delais_accordes = []
        for inv, _ in rows:
            if inv.invoice_date and inv.due_date:
                d = (inv.due_date.replace(tzinfo=None) - inv.invoice_date.replace(tzinfo=None)).days
                if 0 <= d <= 365:
                    delais_accordes.append(d)

        # Retard moyen sur impayés en souffrance (due_date dépassée)
        retards = []
        for inv, _ in rows:
            if inv.status != "paid" and inv.due_date:
                retard = (today - inv.due_date.replace(tzinfo=None)).days
                if retard > 0:
                    retards.append(retard)

        # DSO réel si on a les dates, sinon approximation balance sheet
        has_real_dso = len(delais_reels) > 0
        dso_reel = round(sum(delais_reels) / len(delais_reels)) if delais_reels else None
        dso_approx = round((montant_en_attente / montant_total) * 365, 1) if montant_total > 0 else None

        return {
            "client": client_name or "Tous clients",
            "annee": year,
            "total_factures": total,
            "payees": paid,
            "en_attente": pending,
            "taux_recouvrement_pct": round(paid / total * 100, 1) if total else 0,
            "montant_total_xof": round(montant_total),
            "montant_paye_xof": round(montant_paye),
            "montant_en_attente_xof": round(montant_en_attente),
            "delai_moyen_recouvrement_reel_jours": dso_reel,
            "delai_moyen_accorde_jours": round(sum(delais_accordes) / len(delais_accordes)) if delais_accordes else None,
            "retard_moyen_impayes_jours": round(sum(retards) / len(retards)) if retards else 0,
            "nb_impayes_en_souffrance": len(retards),
            "dso_approx_jours": dso_approx,
            "nb_factures_avec_date_paiement": len(delais_reels),
            "note": (
                f"Délai réel basé sur {len(delais_reels)} facture(s) avec date de paiement Odoo."
                if has_real_dso else
                "Dates de paiement non encore synchronisées — lancer une sync complète pour obtenir le délai réel."
            ),
        }

    async def get_pipeline_stats(self) -> dict:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            sql_total = "SELECT COUNT(*), SUM(expected_revenue), SUM(expected_revenue * probability / 100) FROM opportunities"
            r = (await session.execute(text(sql_total))).fetchone()
            total_nb = r[0] or 0
            total_brut = round(r[1] or 0)
            total_pondere = round(r[2] or 0)

            sql_stage = """
                SELECT stage, COUNT(*) as nb, SUM(expected_revenue) as ca_brut,
                       SUM(expected_revenue * probability / 100) as ca_pondere
                FROM opportunities GROUP BY stage ORDER BY ca_brut DESC
            """
            stages = [
                {"stade": row[0], "nb": row[1], "ca_brut_xof": round(row[2] or 0), "ca_pondere_xof": round(row[3] or 0)}
                for row in (await session.execute(text(sql_stage))).fetchall()
            ]
            sql_seller = """
                SELECT salesperson_name, COUNT(*) as nb, SUM(expected_revenue) as ca_brut
                FROM opportunities WHERE salesperson_name != ''
                GROUP BY salesperson_name ORDER BY ca_brut DESC LIMIT 30
            """
            raw_sellers = [
                {"commercial": row[0], "nb_opportunites": row[1], "ca_potentiel_xof": round(row[2] or 0)}
                for row in (await session.execute(text(sql_seller))).fetchall()
            ]
            # Un même commercial existe parfois sous 2 casses différentes dans Odoo
            # (ex. "Segui Mireille KOUADIO" / "SEGUI MIREILLE KOUADIO") — fusion par
            # nom normalisé pour ne pas scinder ses statistiques en deux lignes.
            sellers = self._merge_by_normalized_name(
                raw_sellers, sum_keys=["nb_opportunites", "ca_potentiel_xof"],
            )[:10]
        return {
            "total_opportunités": total_nb,
            "ca_potentiel_brut_xof": total_brut,
            "ca_potentiel_pondéré_xof": total_pondere,
            "par_stade": stages,
            "par_commercial": sellers,
            "note": "CA pondéré = expected_revenue × probability%. Basé sur le pipeline Odoo synchronisé.",
        }

    async def get_hot_leads(self, limit: int = 10) -> list[dict]:
        from sqlalchemy import text
        sql = """
            SELECT name, client_name, stage, expected_revenue, probability,
                   (expected_revenue * probability / 100) as score_pondere,
                   salesperson_name, deadline
            FROM opportunities
            WHERE probability > 0 AND expected_revenue > 0
            ORDER BY score_pondere DESC LIMIT :limit
        """
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(sql), {"limit": limit})).fetchall()
        return [
            {
                "opportunite": r[0],
                "client": r[1],
                "stade": r[2],
                "revenu_attendu_xof": round(r[3] or 0),
                "probabilite_pct": round(r[4] or 0),
                "score_pondere_xof": round(r[5] or 0),
                "commercial": r[6],
                "deadline": str(r[7]) if r[7] else None,
            }
            for r in rows
        ]

    async def get_revenue_by_salesperson(self, year: int | None = None, quarter: int | None = None) -> list[dict]:
        from sqlalchemy import text
        sql = """
            SELECT salesperson_name,
                   SUM(amount) as ca_total,
                   COUNT(*) as nb_commandes,
                   COUNT(DISTINCT client_id) as nb_clients
            FROM sale_orders
            WHERE salesperson_name IS NOT NULL AND salesperson_name != ''
              AND state NOT IN ('cancel', 'draft')
        """
        params: dict = {}
        if year:
            sql += " AND strftime('%Y', date_order) = :year"
            params["year"] = str(year)
        if quarter:
            months = {1: ("01","02","03"), 2: ("04","05","06"), 3: ("07","08","09"), 4: ("10","11","12")}
            m = months.get(quarter, ("01","12"))
            sql += " AND strftime('%m', date_order) >= :m_start AND strftime('%m', date_order) <= :m_end"
            params["m_start"] = m[0]
            params["m_end"] = m[2] if len(m) > 2 else m[1]
        sql += " GROUP BY salesperson_name ORDER BY ca_total DESC"
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
        raw = [
            {
                "commercial": r[0],
                "ca_total_xof": round(r[1] or 0),
                "nb_commandes": r[2],
                "nb_clients_distincts": r[3],
            }
            for r in rows
        ]
        # Un même commercial existe parfois sous 2 casses différentes dans Odoo —
        # fusion par nom normalisé pour ne pas scinder ses statistiques en deux lignes.
        merged = self._merge_by_normalized_name(
            raw, sum_keys=["ca_total_xof", "nb_commandes", "nb_clients_distincts"],
        )
        for m in merged:
            m["panier_moyen_xof"] = round(m["ca_total_xof"] / m["nb_commandes"]) if m["nb_commandes"] else 0
        return merged

    async def score_client_risk(self, client_id: str | None = None, limit: int = 20) -> list[dict]:
        async with AsyncSessionLocal() as session:
            q = (
                select(InvoiceModel, ClientModel.name.label("client_name"))
                .join(ClientModel, InvoiceModel.client_id == ClientModel.client_id, isouter=True)
            )
            if client_id:
                q = q.where(InvoiceModel.client_id == client_id)
            result = await session.execute(q)
            invoices_rows = result.all()

            from sqlalchemy import func
            last_order_q = select(
                SaleOrderModel.client_id,
                func.max(SaleOrderModel.date_order).label("last_order")
            ).group_by(SaleOrderModel.client_id)
            last_orders = {r[0]: r[1] for r in (await session.execute(last_order_q)).all()}

        today = datetime.utcnow().replace(tzinfo=None)

        by_client: dict = {}
        for inv, cname in invoices_rows:
            cid = inv.client_id
            if cid not in by_client:
                by_client[cid] = {"name": cname or cid, "invoices": []}
            by_client[cid]["invoices"].append(inv)

        scores = []
        for cid, data in by_client.items():
            invs = data["invoices"]
            total = len(invs)
            if total == 0:
                continue
            paid = [i for i in invs if i.status == "paid"]
            unpaid = [i for i in invs if i.status != "paid"]
            montant_total = sum(i.amount for i in invs) or 1
            montant_impaye = sum(i.amount for i in unpaid)
            taux_impayes = montant_impaye / montant_total

            # Score 1 — Ratio impayés (max 30 pts)
            score_unpaid = taux_impayes * 30

            # Score 2 — Ancienneté des impayés en souffrance (max 40 pts) ← clé du fix
            # Un client avec 100% impayés depuis 6+ mois doit atteindre ÉLEVÉ
            overdue_days = []
            for inv in unpaid:
                if inv.due_date:
                    retard = (today - inv.due_date.replace(tzinfo=None)).days
                    if retard > 0:
                        overdue_days.append(retard)
            avg_overdue = sum(overdue_days) / len(overdue_days) if overdue_days else 0
            # 180 jours de retard = 40 pts max (paliers: 30j=8pts, 90j=20pts, 180j=40pts)
            score_overdue = min(40, avg_overdue * (40 / 180))

            # Score 3 — Retard moyen sur factures PAYÉES (max 20 pts)
            delays = []
            for inv in paid:
                if inv.payment_date and inv.due_date:
                    d = (inv.payment_date.replace(tzinfo=None) - inv.due_date.replace(tzinfo=None)).days
                    delays.append(max(0, d))
            avg_delay = sum(delays) / len(delays) if delays else 0
            score_delay = min(20, avg_delay * (20 / 25))  # 25 jours retard = 20 pts max

            # Score 4 — Inactivité commerciale (max 10 pts)
            last_order = last_orders.get(cid)
            if last_order:
                mois_inactif = (today - last_order.replace(tzinfo=None)).days / 30
                score_inactive = min(10, mois_inactif * (10 / 6))
            else:
                score_inactive = 10

            risk_score = round(score_unpaid + score_overdue + score_delay + score_inactive)
            scores.append({
                "client": data["name"],
                "client_id": cid,
                "score_risque": risk_score,
                "niveau": "ÉLEVÉ" if risk_score >= 60 else ("MODÉRÉ" if risk_score >= 30 else "FAIBLE"),
                "détail": {
                    "taux_impayes_pct": round(taux_impayes * 100, 1),
                    "retard_moyen_impayes_jours": round(avg_overdue),
                    "retard_moyen_paiement_jours": round(avg_delay),
                    "mois_sans_commande": round((today - last_order.replace(tzinfo=None)).days / 30, 1) if last_order else None,
                    "montant_impaye_xof": round(montant_impaye),
                },
            })

        scores.sort(key=lambda x: x["score_risque"], reverse=True)
        return scores[:limit]

    async def get_revenue_by_sector(self, year: int | None = None, limit: int = 20) -> list[dict]:
        from sqlalchemy import text
        sql = """
            SELECT COALESCE(c.sector, 'Non renseigné') as secteur,
                   SUM(o.amount) as ca_total,
                   COUNT(DISTINCT o.client_id) as nb_clients,
                   COUNT(*) as nb_commandes
            FROM sale_orders o
            LEFT JOIN clients c ON o.client_id = c.client_id
            WHERE o.state NOT IN ('cancel', 'draft')
        """
        params: dict = {}
        if year:
            sql += " AND strftime('%Y', o.date_order) = :year"
            params["year"] = str(year)
        sql += " GROUP BY secteur ORDER BY ca_total DESC LIMIT :limit"
        params["limit"] = limit
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
        return [
            {
                "secteur": r[0],
                "ca_total_xof": round(r[1] or 0),
                "nb_clients": r[2],
                "nb_commandes": r[3],
                "panier_moyen_client_xof": round((r[1] or 0) / r[2]) if r[2] else 0,
            }
            for r in rows
        ]

    async def get_quarterly_forecast(self, year: int | None = None) -> dict:
        from sqlalchemy import text
        from datetime import datetime as dt
        current_year = year or dt.now().year
        current_month = dt.now().month
        current_quarter = (current_month - 1) // 3 + 1
        q_months = {1: range(1, 4), 2: range(4, 7), 3: range(7, 10), 4: range(10, 13)}
        quarter_months = list(q_months[current_quarter])

        # CA mensuel sur les 12 derniers mois
        sql = """
            SELECT strftime('%Y', date_order) as yr, strftime('%m', date_order) as mo,
                   SUM(amount) as ca
            FROM sale_orders
            WHERE state NOT IN ('cancel', 'draft')
              AND date_order >= date('now', '-12 months')
            GROUP BY yr, mo ORDER BY yr, mo
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql))
            monthly = {(int(r[0]), int(r[1])): float(r[2] or 0) for r in result.fetchall()}

        # Mois déjà passés + mois en cours (données partielles)
        done_months = [(current_year, m) for m in quarter_months if m < current_month]
        current_month_ca = monthly.get((current_year, current_month), 0)  # mois en cours (partiel)
        remaining_months = [(current_year, m) for m in quarter_months if m > current_month]
        realise = sum(monthly.get(m, 0) for m in done_months) + current_month_ca

        # Tendance : moyenne pondérée des 6 derniers mois disponibles
        last_6 = sorted([(k, v) for k, v in monthly.items()], key=lambda x: x[0])[-6:]
        if len(last_6) >= 2:
            values = [v for _, v in last_6]
            # Régression linéaire simple
            n = len(values)
            mean_x = (n - 1) / 2
            mean_y = sum(values) / n
            num = sum((i - mean_x) * (values[i] - mean_y) for i in range(n))
            den = sum((i - mean_x) ** 2 for i in range(n))
            slope = num / den if den else 0
            intercept = mean_y - slope * mean_x
            trend_next = intercept + slope * n
        else:
            trend_next = sum(v for _, v in last_6) / len(last_6) if last_6 else 0

        projection_realiste = realise + trend_next * len(remaining_months)
        projection_optimiste = realise + trend_next * len(remaining_months) * 1.15
        projection_pessimiste = realise + trend_next * len(remaining_months) * 0.85

        current_day = dt.now().day
        import calendar
        days_in_month = calendar.monthrange(current_year, current_month)[1]
        return {
            "trimestre": f"Q{current_quarter} {current_year}",
            "mois_trimestre": [f"{m:02d}/{current_year}" for m in quarter_months],
            "realise_a_ce_jour_xof": round(realise),
            "detail_realise": {
                "mois_complets": [f"{m[1]:02d}/{m[0]}" for m in done_months],
                "mois_en_cours": f"{current_month:02d}/{current_year} (jour {current_day}/{days_in_month}, partiel)",
                "ca_mois_en_cours_xof": round(current_month_ca),
            },
            "mois_restants_a_projeter": len(remaining_months),
            "tendance_mensuelle_xof": round(trend_next),
            "projection_fin_trimestre": {
                "optimiste_xof": round(projection_optimiste),
                "realiste_xof": round(projection_realiste),
                "pessimiste_xof": round(projection_pessimiste),
            },
            "note": f"Réalisé = mois complets + {current_day} jours de {current_month:02d}/{current_year}. Projection sur {len(remaining_months)} mois restant(s). Tendance calculée sur {len(last_6)} mois.",
        }

    async def get_cross_sell_opportunities(self, product_anchor: str, product_target: str | None = None, limit: int = 20) -> list[dict]:
        from sqlalchemy import text
        # Clients ayant acheté product_anchor
        sql_anchor = """
            SELECT DISTINCT o.client_id, o.client_name,
                   MAX(o.date_order) as last_anchor_purchase,
                   COUNT(*) as nb_achats_anchor
            FROM sale_orders o, json_each(o.order_lines) j
            WHERE lower(json_extract(j.value, '$.product')) LIKE lower(:anchor)
              AND o.state NOT IN ('cancel', 'draft')
            GROUP BY o.client_id, o.client_name
        """
        async with AsyncSessionLocal() as session:
            anchor_rows = (await session.execute(text(sql_anchor), {"anchor": f"%{product_anchor}%"})).fetchall()
            anchor_clients = {r[0]: {"name": r[1], "last_purchase": r[2], "nb_achats": r[3]} for r in anchor_rows}

            if not anchor_clients:
                return []

            if product_target:
                # Clients qui ont AUSSI acheté product_target
                sql_target = """
                    SELECT DISTINCT o.client_id FROM sale_orders o, json_each(o.order_lines) j
                    WHERE lower(json_extract(j.value, '$.product')) LIKE lower(:target)
                      AND o.state NOT IN ('cancel', 'draft')
                """
                target_rows = (await session.execute(text(sql_target), {"target": f"%{product_target}%"})).fetchall()
                already_bought = {r[0] for r in target_rows}
            else:
                already_bought = set()

        results = []
        for cid, info in anchor_clients.items():
            if cid in already_bought:
                continue
            results.append({
                "client": info["name"],
                "client_id": cid,
                "dernier_achat_anchor": info["last_purchase"],
                "nb_achats_anchor": info["nb_achats"],
                "opportunite": f"A acheté '{product_anchor}'" + (f" mais pas '{product_target}'" if product_target else ""),
            })

        results.sort(key=lambda x: x["nb_achats_anchor"], reverse=True)
        return results[:limit]

    async def search_orders_by_product(self, product_query: str, year: int | None = None) -> list[dict]:
        import json as _json
        from sqlalchemy import text
        sql = """
            SELECT DISTINCT o.name, o.client_name, o.amount, o.date_order, o.state,
                   json_group_array(json_object(
                       'product', json_extract(j.value, '$.product'),
                       'qty', json_extract(j.value, '$.qty'),
                       'subtotal', json_extract(j.value, '$.subtotal')
                   )) as matching_lines
            FROM sale_orders o, json_each(o.order_lines) j
            WHERE lower(json_extract(j.value, '$.product')) LIKE lower(:query)
        """
        params: dict = {"query": f"%{product_query}%"}
        if year:
            sql += " AND strftime('%Y', o.date_order) = :year"
            params["year"] = str(year)
        sql += " GROUP BY o.name ORDER BY o.date_order DESC LIMIT 50"
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
        return [
            {
                "ref": r[0],
                "client": r[1],
                "montant_xof": r[2],
                "date": r[3],
                "état": r[4],
                "lignes_correspondantes": _json.loads(r[5]) if r[5] else [],
            }
            for r in rows
        ]

    async def get_revenue_by_product(self, year: int | None = None, limit: int = 30) -> list[dict]:
        from sqlalchemy import text
        sql = """
            SELECT json_extract(j.value, '$.product') as product,
                   SUM(CAST(json_extract(j.value, '$.subtotal') AS REAL)) as total_revenue,
                   COUNT(DISTINCT o.order_id) as order_count,
                   SUM(CAST(json_extract(j.value, '$.qty') AS REAL)) as qty_total
            FROM sale_orders o, json_each(o.order_lines) j
            WHERE json_extract(j.value, '$.product') IS NOT NULL
              AND json_extract(j.value, '$.subtotal') > 0
        """
        params: dict = {}
        if year:
            sql += " AND strftime('%Y', o.date_order) = :year"
            params["year"] = str(year)
        sql += " GROUP BY product ORDER BY total_revenue DESC LIMIT :limit"
        params["limit"] = limit
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
        return [
            {
                "produit": r[0],
                "ca_total_xof": round(r[1] or 0),
                "nb_commandes": r[2],
                "quantite_totale": round(r[3] or 0),
            }
            for r in rows
        ]

    async def get_client_retention(self, year: int | None = None) -> dict:
        """
        Calcule la rétention, le churn et les nouveaux clients entre deux années consécutives.
        Retourne aussi la liste détaillée des clients perdus et des nouveaux clients.
        """
        from sqlalchemy import text
        from datetime import datetime as dt
        year_cible = year or dt.now().year
        year_ref = year_cible - 1

        async with AsyncSessionLocal() as session:
            # Clients actifs en année de référence (N-1)
            sql_ref = """
                SELECT DISTINCT o.client_id, c.name
                FROM sale_orders o
                LEFT JOIN clients c ON o.client_id = c.client_id
                WHERE strftime('%Y', o.date_order) = :yr
                  AND o.state NOT IN ('cancel', 'draft')
            """
            rows_ref = (await session.execute(text(sql_ref), {"yr": str(year_ref)})).fetchall()
            clients_ref = {r[0]: r[1] or r[0] for r in rows_ref}

            # Clients actifs en année cible (N)
            rows_cible = (await session.execute(text(sql_ref), {"yr": str(year_cible)})).fetchall()
            clients_cible = {r[0]: r[1] or r[0] for r in rows_cible}

        ref_ids = set(clients_ref.keys())
        cible_ids = set(clients_cible.keys())

        retained_ids = ref_ids & cible_ids
        churned_ids = ref_ids - cible_ids
        new_ids = cible_ids - ref_ids

        retention_rate = round(len(retained_ids) / len(ref_ids) * 100, 1) if ref_ids else 0
        churn_rate = round(len(churned_ids) / len(ref_ids) * 100, 1) if ref_ids else 0

        return {
            "annee_reference": year_ref,
            "annee_cible": year_cible,
            "clients_actifs_annee_ref": len(ref_ids),
            "clients_actifs_annee_cible": len(cible_ids),
            "clients_retenus": len(retained_ids),
            "taux_retention_pct": retention_rate,
            "clients_perdus_churn": len(churned_ids),
            "taux_churn_pct": churn_rate,
            "nouveaux_clients": len(new_ids),
            "liste_clients_perdus": sorted([clients_ref[cid] for cid in churned_ids])[:30],
            "liste_nouveaux_clients": sorted([clients_cible[cid] for cid in new_ids])[:30],
            "note": (
                f"Rétention = clients ayant commandé en {year_ref} ET {year_cible}. "
                f"Churn = actifs en {year_ref} sans aucune commande en {year_cible}. "
                f"Nouveaux = première commande en {year_cible} (jamais commandé en {year_ref})."
            ),
        }

    async def sync_from_odoo(self) -> dict:
        logger.warning("LocalCRMAdapter.sync_from_odoo() délégué à OdooSyncJob")
        return {}

    # ── Dossiers commerciaux ──────────────────────────────────────────────────

    @staticmethod
    def _dossier_to_dict(d: DossierModel) -> dict:
        return {
            "ref": d.dossier_ref,
            "client": d.client_name,
            "projet": d.project_name or "",
            "commercial": d.salesperson or "",
            "etat": d.state,
            "date_creation": d.date_creation.strftime("%d/%m/%Y") if d.date_creation else None,
            "date_fin": d.date_end_project.strftime("%d/%m/%Y") if d.date_end_project else None,
            "ca_provisoire": d.ca_provisoire,
            "ca_definitif": d.ca_definitif,
            "depense_provisoire": d.depense_provisoire,
            "depense_definitive": d.depense_definitive,
            "marge_provisoire": d.marge_provisoire,
            "marge_definitive": d.marge_definitive,
            "marge_previsionnelle": d.marge_previsionnelle,
            "perc_marge_provisoire": round(d.perc_marge_provisoire, 2),
            "perc_marge_definitive": round(d.perc_marge_definitive, 2),
            "perc_marge_previsionnelle": round(d.perc_marge_previsionnelle, 2),
            "montant_recu": d.montant_recu,
            "reste_a_encaisser": d.reste_a_encaisser,
            "backlog": d.backlog,
            "fournisseurs_payes": d.fournisseurs_payes,
            "fournisseurs_restant": d.fournisseurs_restant,
            "nb_bdc": d.nb_bdc,
            "nb_factures_client": d.nb_factures_client,
            "nb_factures_fournisseur": d.nb_factures_fournisseur,
        }

    async def get_dossier(self, ref: str) -> dict | None:
        """Récupère un dossier par sa référence (DC/YYYY/XXXX) ou par référence BDC (FP/...)."""
        async with AsyncSessionLocal() as session:
            # Chercher directement par ref dossier
            if ref.upper().startswith("DC/"):
                row = await session.get(DossierModel, ref.upper())
                if row:
                    return self._dossier_to_dict(row)
                return None
            # Chercher par référence BDC (FP/YYYY/XXXX)
            r = await session.execute(
                select(SaleOrderModel).where(SaleOrderModel.name == ref.upper())
            )
            so = r.scalar_one_or_none()
            if so and so.dossier_id:
                row = await session.get(DossierModel, so.dossier_id)
                if row:
                    return self._dossier_to_dict(row)
            return None

    async def get_dossiers_by_client(self, client_name: str, year: int | None = None) -> list[dict]:
        """Tous les dossiers d'un client (recherche partielle sur le nom)."""
        from sqlalchemy import extract
        async with AsyncSessionLocal() as session:
            q = select(DossierModel).where(
                DossierModel.client_name.ilike(f"%{client_name}%")
            )
            if year:
                q = q.where(extract("year", DossierModel.date_creation) == year)
            q = q.order_by(DossierModel.date_creation.desc()).limit(50)
            result = await session.execute(q)
            return [self._dossier_to_dict(d) for d in result.scalars()]

    async def get_margin_stats(self, year: int | None = None) -> dict:
        """Statistiques globales de marge : CA prov, CA def, marge prov, marge def, % moyens."""
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            year_filter = "AND strftime('%Y', date_creation) = :year" if year else ""
            params = {"year": str(year)} if year else {}
            sql = text(f"""
                SELECT
                    COUNT(*) nb_dossiers,
                    SUM(ca_provisoire) total_ca_provisoire,
                    SUM(ca_definitif) total_ca_definitif,
                    SUM(marge_provisoire) total_marge_provisoire,
                    SUM(marge_definitive) total_marge_definitive,
                    AVG(CASE WHEN ca_provisoire > 0 THEN perc_marge_provisoire END) avg_perc_marge_prov,
                    AVG(CASE WHEN ca_definitif > 0 THEN perc_marge_definitive END) avg_perc_marge_def,
                    SUM(montant_recu) total_recu,
                    SUM(reste_a_encaisser) total_reste,
                    SUM(backlog) total_backlog,
                    SUM(fournisseurs_payes) total_four_payes,
                    SUM(fournisseurs_restant) total_four_restant
                FROM dossiers
                WHERE 1=1 {year_filter}
            """)
            row = (await session.execute(sql, params)).fetchone()
            return {
                "annee": year or "toutes",
                "nb_dossiers": row[0] or 0,
                "ca_provisoire_total": row[1] or 0,
                "ca_definitif_total": row[2] or 0,
                "marge_provisoire_total": row[3] or 0,
                "marge_definitive_total": row[4] or 0,
                "perc_marge_provisoire_moyen": round(row[5] or 0, 2),
                "perc_marge_definitive_moyen": round(row[6] or 0, 2),
                "total_encaisse": row[7] or 0,
                "reste_a_encaisser": row[8] or 0,
                "backlog_total": row[9] or 0,
                "fournisseurs_payes": row[10] or 0,
                "fournisseurs_restant": row[11] or 0,
            }

    async def get_top_margin_dossiers(self, limit: int = 10, year: int | None = None,
                                      metric: str = "marge_provisoire") -> list[dict]:
        """Top dossiers par marge (provisoire ou définitive)."""
        from sqlalchemy import text
        valid = {"marge_provisoire", "marge_definitive", "perc_marge_provisoire", "perc_marge_definitive", "ca_provisoire"}
        col = metric if metric in valid else "marge_provisoire"
        year_filter = "AND strftime('%Y', date_creation) = :year" if year else ""
        params: dict = {"limit": limit}
        if year:
            params["year"] = str(year)
        async with AsyncSessionLocal() as session:
            sql = text(f"""
                SELECT dossier_ref, client_name, project_name, salesperson, state,
                       ca_provisoire, ca_definitif, marge_provisoire, marge_definitive,
                       perc_marge_provisoire, perc_marge_definitive, date_creation
                FROM dossiers
                WHERE ca_provisoire > 0 {year_filter}
                ORDER BY {col} DESC
                LIMIT :limit
            """)
            rows = (await session.execute(sql, params)).fetchall()
            return [
                {
                    "ref": r[0], "client": r[1], "projet": r[2] or "", "commercial": r[3] or "",
                    "etat": r[4],
                    "ca_provisoire": r[5], "ca_definitif": r[6],
                    "marge_provisoire": r[7], "marge_definitive": r[8],
                    "perc_marge_prov": round(r[9], 1), "perc_marge_def": round(r[10], 1),
                    "date": r[11][:10] if r[11] else None,
                }
                for r in rows
            ]

    # ---- Normalisation des stades d'opportunité (les libellés Odoo varient :
    #      "6-Gagné"/"Won", "7-Perdu"/"Perdu", "1-Qualification"/"Qualified"…) ----
    _STAGE_CANON = [
        ("gagn|won", "__won__"),
        ("perdu|lost", "__lost__"),
        ("annul|cancel", "__cancelled__"),
        ("suspend", "__suspended__"),
        ("new|prospect", "Prospection"),
        ("qualif", "Qualification"),
        ("montage", "Montage"),
        ("transmise", "Transmise"),
        ("proposition", "Proposition"),
        ("n[ée]gociation", "Négociation"),
        ("contractualisation", "Contractualisation"),
    ]
    # Ordre d'affichage du pipeline ouvert (celui du cockpit)
    OPEN_STAGE_ORDER = [
        "Prospection", "Qualification", "Montage", "Transmise",
        "Proposition", "Négociation", "Contractualisation",
    ]

    @classmethod
    def _canon_stage(cls, stage: str) -> str:
        import re
        s = (stage or "").strip().lower()
        for pattern, canon in cls._STAGE_CANON:
            if re.search(pattern, s):
                return canon
        return "Autre"

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Clé de fusion insensible à la casse/aux espaces — un même commercial
        existe parfois sous plusieurs variantes de casse dans Odoo
        (ex. "Segui Mireille KOUADIO" / "SEGUI MIREILLE KOUADIO")."""
        import re
        return re.sub(r"\s+", " ", (name or "").strip().upper())

    @classmethod
    def _merge_by_normalized_name(cls, rows: list[dict], *, sum_keys: list[str], name_key: str = "commercial") -> list[dict]:
        """Fusionne les lignes dont le nom ne diffère que par la casse/espaces,
        en sommant `sum_keys` et en gardant comme libellé la variante la plus
        fréquente (approximée par la plus grosse valeur du premier sum_key)."""
        merged: dict[str, dict] = {}
        for row in rows:
            key = cls._normalize_name(row[name_key])
            if key not in merged:
                merged[key] = {**row, "_display_weight": row[sum_keys[0]]}
                continue
            m = merged[key]
            for sk in sum_keys:
                m[sk] = m[sk] + row[sk]
            if row[sum_keys[0]] > m["_display_weight"]:
                m[name_key] = row[name_key]
                m["_display_weight"] = row[sum_keys[0]]
        result = list(merged.values())
        for r in result:
            del r["_display_weight"]
        result.sort(key=lambda r: r[sum_keys[0]], reverse=True)
        return result

    async def get_open_pipeline_stats(self) -> dict:
        """Pipeline OUVERT uniquement (exclut gagné/perdu/annulé/suspendu), stades normalisés."""
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text("""
                SELECT stage, COUNT(*), SUM(expected_revenue),
                       SUM(expected_revenue * probability / 100),
                       SUM(CASE WHEN created_at IS NOT NULL
                                 AND julianday('now') - julianday(created_at) > 365
                            THEN 1 ELSE 0 END)
                FROM opportunities GROUP BY stage
            """))).fetchall()

        closed = {"__won__", "__lost__", "__cancelled__", "__suspended__"}
        by_stage: dict[str, dict] = {}
        total_nb = total_brut = total_pondere = total_vieilles = 0
        for stage, nb, brut, pondere, vieilles in rows:
            canon = self._canon_stage(stage)
            if canon in closed:
                continue
            entry = by_stage.setdefault(canon, {"stade": canon, "nb": 0, "ca_brut_xof": 0, "ca_pondere_xof": 0})
            entry["nb"] += nb
            entry["ca_brut_xof"] += round(brut or 0)
            entry["ca_pondere_xof"] += round(pondere or 0)
            total_nb += nb
            total_brut += round(brut or 0)
            total_pondere += round(pondere or 0)
            total_vieilles += vieilles or 0

        ordered = [by_stage[s] for s in self.OPEN_STAGE_ORDER if s in by_stage]
        ordered += [v for k, v in by_stage.items() if k not in self.OPEN_STAGE_ORDER]
        return {
            "total_opportunites": total_nb,
            "ca_brut_xof": total_brut,
            "ca_pondere_xof": total_pondere,
            "plus_un_an_nb": int(total_vieilles),
            "plus_un_an_pct": round(total_vieilles / total_nb * 100) if total_nb else 0,
            "par_stade": ordered,
        }

    async def get_win_rate(self) -> dict:
        """Taux de transformation réel : opportunités gagnées vs perdues (historique complet)."""
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(
                "SELECT stage, COUNT(*), SUM(expected_revenue) FROM opportunities GROUP BY stage"
            ))).fetchall()

        won_nb = lost_nb = 0
        won_val = lost_val = 0.0
        for stage, nb, val in rows:
            canon = self._canon_stage(stage)
            if canon == "__won__":
                won_nb += nb
                won_val += val or 0
            elif canon == "__lost__":
                lost_nb += nb
                lost_val += val or 0

        closed = won_nb + lost_nb
        closed_val = won_val + lost_val
        return {
            "gagnees_nb": won_nb,
            "perdues_nb": lost_nb,
            "taux_nb_pct": round(won_nb / closed * 100, 1) if closed else 0,
            "gagnees_valeur_xof": round(won_val),
            "perdues_valeur_xof": round(lost_val),
            "taux_valeur_pct": round(won_val / closed_val * 100, 1) if closed_val else 0,
        }

    async def get_lost_deals(self, limit: int = 20) -> dict:
        """Opportunités perdues (historique) : top N + agrégats par client et par commercial."""
        from sqlalchemy import text
        sql = "SELECT name, client_name, stage, expected_revenue, salesperson_name FROM opportunities"
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(sql))).fetchall()

        lost = [
            {
                "name": r[0],
                "client": r[1] or "—",
                "montant_xof": round(r[3] or 0),
                "commercial": r[4] or "",
            }
            for r in rows if self._canon_stage(r[2]) == "__lost__"
        ]

        by_client: dict[str, dict] = {}
        for d in lost:
            c = by_client.setdefault(d["client"], {"client": d["client"], "nb": 0, "montant_xof": 0})
            c["nb"] += 1
            c["montant_xof"] += d["montant_xof"]

        by_commercial_raw: dict[str, dict] = {}
        for d in lost:
            if not d["commercial"]:
                continue
            c = by_commercial_raw.setdefault(d["commercial"], {"commercial": d["commercial"], "nb": 0, "montant_xof": 0})
            c["nb"] += 1
            c["montant_xof"] += d["montant_xof"]
        # Un même commercial existe parfois sous 2 casses différentes dans Odoo —
        # fusion par nom normalisé pour ne pas scinder ses statistiques en deux lignes.
        by_commercial = self._merge_by_normalized_name(
            list(by_commercial_raw.values()), sum_keys=["montant_xof", "nb"],
        )

        top_deals = sorted(lost, key=lambda d: d["montant_xof"], reverse=True)[:limit]
        return {
            "nb_total": len(lost),
            "montant_total_xof": sum(d["montant_xof"] for d in lost),
            "top_deals": top_deals,
            "by_client": sorted(by_client.values(), key=lambda c: c["montant_xof"], reverse=True),
            "by_commercial": by_commercial,
        }

    async def get_order_lines(self, limit: int = 20000) -> list[dict]:
        """Lignes de commande réelles (sale_orders non annulées). Pas de tri par
        date/LIMIT restrictif utile ici : les analyses transversales (montée en
        valeur) ont besoin de voir aussi les commandes anciennes (obsolescence)."""
        from sqlalchemy import text
        sql = """
            SELECT o.client_id, o.client_name,
                   json_extract(j.value, '$.product') as product,
                   CAST(json_extract(j.value, '$.subtotal') AS REAL) as subtotal,
                   o.date_order
            FROM sale_orders o, json_each(o.order_lines) j
            WHERE o.state NOT IN ('cancel', 'draft')
              AND json_extract(j.value, '$.product') IS NOT NULL
            LIMIT :limit
        """
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(sql), {"limit": limit})).fetchall()
        return [
            {
                "client_id": r[0],
                "client": r[1] or "—",
                "product": r[2],
                "subtotal_xof": r[3] or 0,
                "date_order": r[4],
            }
            for r in rows
        ]

    async def get_top_suppliers(self, limit: int = 20) -> list[dict]:
        """Fournisseurs réels (purchase_orders, synchronisés depuis Odoo). Pas de
        notion de dette/impayé ici : seules les factures clients (out_invoice)
        sont synchronisées, pas les factures fournisseurs (in_invoice) — voir
        [[operations-dirops-module]]. L'« engagement » exposé est donc calculé
        sur les commandes d'achat réelles (montant, ancienneté, activité récente),
        jamais un solde comptable inventé."""
        from sqlalchemy import text
        depuis_12m = (datetime.utcnow() - timedelta(days=365)).isoformat()
        sql = """
            SELECT client_name, SUM(amount), COUNT(*), MAX(date_order), MIN(date_order),
                   SUM(CASE WHEN date_order >= :depuis_12m THEN amount ELSE 0 END),
                   COUNT(CASE WHEN date_order >= :depuis_12m THEN 1 END)
            FROM purchase_orders
            WHERE client_name IS NOT NULL AND client_name != ''
            GROUP BY client_name
            ORDER BY SUM(amount) DESC
            LIMIT :limit
        """
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(sql), {"limit": limit, "depuis_12m": depuis_12m})).fetchall()
            suppliers = []
            for name, total, nb, last_date, first_date, montant_12m, nb_12m in rows:
                detail_sql = """
                    SELECT name, amount, date_order FROM purchase_orders
                    WHERE client_name = :name
                    ORDER BY date_order DESC LIMIT 5
                """
                detail_rows = (await session.execute(text(detail_sql), {"name": name})).fetchall()
                suppliers.append({
                    "name": name,
                    "montant_total_xof": round(total or 0),
                    "nb_commandes": nb,
                    "derniere_commande": last_date[:10] if last_date else None,
                    "premiere_commande": first_date[:10] if first_date else None,
                    "montant_moyen_xof": round((total or 0) / nb) if nb else 0,
                    "montant_engage_12m_xof": round(montant_12m or 0),
                    "nb_commandes_12m": nb_12m or 0,
                    "commandes_recentes": [
                        {"ref": r[0], "montant_xof": round(r[1] or 0), "date": r[2][:10] if r[2] else None}
                        for r in detail_rows
                    ],
                })
        return suppliers

    async def get_supplier_intelligence(self, limit: int = 20) -> list[dict]:
        """5 indicateurs différenciants pour un DAF/DG d'ESN — pas la répétition de ce
        qu'Odoo montre déjà (montant/nb commandes, cf. get_top_suppliers), mais des
        croisements qu'Odoo ne fait pas :
        1. Ligne de crédit vs encours réellement dû (factures fournisseurs non soldées).
        2. Cash prévisionnel à 30/60/90j sur les échéances réelles.
        3. Marge de sous-traitance : marge des dossiers dont ce fournisseur a des achats liés.
        4. Fiabilité de paiement : retard réel constaté vs délai négocié.
        5. Risque de rupture (proxy) : dossiers ACTIFS où ce fournisseur est le SEUL sur
           les achats liés — pas une vraie donnée de vivier/remplacement (absente
           d'Odoo), affiché comme un signal, pas une certitude.
        """
        from sqlalchemy import text
        now = datetime.utcnow()

        async with AsyncSessionLocal() as session:
            # ── Base : volume d'achats par fournisseur (pour le taux de dépendance) ──
            base_rows = (await session.execute(text("""
                SELECT client_name, SUM(amount), COUNT(*)
                FROM purchase_orders
                WHERE client_name IS NOT NULL AND client_name != ''
                GROUP BY client_name
                ORDER BY SUM(amount) DESC
                LIMIT :limit
            """), {"limit": limit})).fetchall()
            total_achats = (await session.execute(text(
                "SELECT SUM(amount) FROM purchase_orders"
            ))).scalar() or 0

            result = []
            for name, montant_total, nb_commandes in base_rows:
                # ── Fiche fournisseur (crédit, délai négocié) — jointure par NOM, best
                # effort : purchase_orders ne stocke que client_name/client_id (le
                # partner_id vendeur), suppliers.supplier_id est le MÊME partner_id.
                sup_row = (await session.execute(
                    select(SupplierModel).where(SupplierModel.name == name)
                )).scalar_one_or_none()
                credit_limit = sup_row.credit_limit if sup_row else None
                use_credit_limit = bool(sup_row.use_partner_credit_limit) if sup_row else False
                payment_term_name = sup_row.payment_term_name if sup_row else None
                payment_term_days = sup_row.payment_term_days if sup_row else None
                supplier_id = sup_row.supplier_id if sup_row else None

                # ── 1. Ligne de crédit vs encours dû ────────────────────────────────
                encours_du = 0.0
                if supplier_id:
                    encours_du = (await session.execute(text("""
                        SELECT COALESCE(SUM(amount_residual), 0) FROM supplier_invoices
                        WHERE supplier_id = :sid AND payment_state != 'paid'
                    """), {"sid": supplier_id})).scalar() or 0.0
                taux_consommation = (
                    round(encours_du / credit_limit * 100, 1)
                    if credit_limit and use_credit_limit and credit_limit > 0
                    else None
                )

                # ── 2. Cash prévisionnel 30/60/90j (échéances réelles, factures ouvertes) ──
                cash_30 = cash_60 = cash_90 = cash_plus = 0.0
                if supplier_id:
                    open_invoices = (await session.execute(text("""
                        SELECT due_date, amount_residual FROM supplier_invoices
                        WHERE supplier_id = :sid AND payment_state != 'paid' AND amount_residual > 0
                    """), {"sid": supplier_id})).fetchall()
                    for due_date, residual in open_invoices:
                        if not due_date:
                            cash_plus += residual or 0
                            continue
                        due_dt = due_date if isinstance(due_date, datetime) else datetime.fromisoformat(str(due_date))
                        jours = (due_dt - now).days
                        if jours <= 30:
                            cash_30 += residual or 0
                        elif jours <= 60:
                            cash_60 += residual or 0
                        elif jours <= 90:
                            cash_90 += residual or 0
                        else:
                            cash_plus += residual or 0

                # ── 3. Marge de sous-traitance (dossiers reliés via purchase_orders.dossier_id) ──
                marge_sous_traitance = 0.0
                nb_dossiers_lies = 0
                if name:
                    dossier_rows = (await session.execute(text("""
                        SELECT DISTINCT d.dossier_ref,
                               CASE WHEN d.marge_definitive != 0 THEN d.marge_definitive
                                    WHEN d.marge_provisoire != 0 THEN d.marge_provisoire
                                    ELSE d.marge_previsionnelle END AS marge
                        FROM purchase_orders po
                        JOIN dossiers d ON po.dossier_id = d.dossier_ref
                        WHERE po.client_name = :name AND po.dossier_id IS NOT NULL
                    """), {"name": name})).fetchall()
                    nb_dossiers_lies = len(dossier_rows)
                    marge_sous_traitance = sum(m or 0 for _, m in dossier_rows)

                # ── 4. Fiabilité de paiement : retard réel vs délai négocié ─────────
                retard_moyen_jours = None
                if supplier_id:
                    paid_rows = (await session.execute(text("""
                        SELECT due_date, payment_date FROM supplier_invoices
                        WHERE supplier_id = :sid AND payment_date IS NOT NULL AND due_date IS NOT NULL
                    """), {"sid": supplier_id})).fetchall()
                    if paid_rows:
                        ecarts = []
                        for due_date, payment_date in paid_rows:
                            due_dt = due_date if isinstance(due_date, datetime) else datetime.fromisoformat(str(due_date))
                            pay_dt = payment_date if isinstance(payment_date, datetime) else datetime.fromisoformat(str(payment_date))
                            ecarts.append((pay_dt - due_dt).days)
                        retard_moyen_jours = round(sum(ecarts) / len(ecarts), 1)

                # ── 5. Risque de rupture (proxy) : dossiers actifs à fournisseur unique ──
                dossiers_a_risque = 0
                if name:
                    risk_rows = (await session.execute(text("""
                        SELECT po.dossier_id, COUNT(DISTINCT po.client_name) as nb_fournisseurs
                        FROM purchase_orders po
                        JOIN dossiers d ON po.dossier_id = d.dossier_ref
                        WHERE po.dossier_id IS NOT NULL AND d.state = 'confirmed'
                        GROUP BY po.dossier_id
                        HAVING nb_fournisseurs = 1
                    """))).fetchall()
                    dossiers_uniques = {row[0] for row in risk_rows}
                    if dossiers_uniques:
                        mine = (await session.execute(text("""
                            SELECT DISTINCT dossier_id FROM purchase_orders
                            WHERE client_name = :name AND dossier_id IS NOT NULL
                        """), {"name": name})).fetchall()
                        dossiers_a_risque = len({r[0] for r in mine} & dossiers_uniques)

                result.append({
                    "name": name,
                    "montant_total_xof": round(montant_total or 0),
                    "nb_commandes": nb_commandes,
                    "taux_dependance_pct": round((montant_total or 0) / total_achats * 100, 1) if total_achats else 0,
                    "credit_limit_xof": round(credit_limit) if credit_limit else None,
                    "encours_du_xof": round(encours_du),
                    "taux_consommation_credit_pct": taux_consommation,
                    "cash_30j_xof": round(cash_30),
                    "cash_60j_xof": round(cash_60),
                    "cash_90j_xof": round(cash_90),
                    "cash_plus_90j_xof": round(cash_plus),
                    "marge_sous_traitance_xof": round(marge_sous_traitance),
                    "nb_dossiers_lies": nb_dossiers_lies,
                    "payment_term_name": payment_term_name,
                    "payment_term_days": payment_term_days,
                    "retard_moyen_jours": retard_moyen_jours,
                    "dossiers_a_risque_fournisseur_unique": dossiers_a_risque,
                })
        return result

    async def get_client_portfolio(self, limit: int = 50) -> list[dict]:
        """Portefeuille clients réel, agrégé sur la table dossiers (CA, backlog,
        reste à encaisser, nb dossiers) — enrichi du secteur/contact quand la
        fiche client correspondante existe (jointure par nom, best-effort)."""
        from sqlalchemy import text
        # CA par dossier = définitif s'il est arrêté, sinon provisoire (estimation) —
        # jamais les deux additionnés (même dossier, pas deux CA distincts à cumuler).
        ca_expr = "CASE WHEN ca_definitif > 0 THEN ca_definitif ELSE ca_provisoire END"
        sql = f"""
            SELECT client_name,
                   COUNT(*) as nb_dossiers,
                   SUM({ca_expr}) as ca_total,
                   SUM(reste_a_encaisser) as reste_a_encaisser_total,
                   SUM(backlog) as backlog_total,
                   MIN(date_creation) as premiere_commande,
                   MAX(date_creation) as derniere_commande
            FROM dossiers
            WHERE client_name IS NOT NULL AND client_name != ''
            GROUP BY client_name
            ORDER BY SUM({ca_expr}) DESC
            LIMIT :limit
        """
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(sql), {"limit": limit})).fetchall()
            result = []
            for r in rows:
                client_row = (await session.execute(
                    text("SELECT sector, contact_email, phone FROM clients WHERE name = :name LIMIT 1"),
                    {"name": r[0]},
                )).fetchone()
                proj_row = (await session.execute(
                    text("""
                        SELECT project_name FROM dossiers
                        WHERE client_name = :name AND project_name IS NOT NULL AND project_name != ''
                        ORDER BY date_creation DESC LIMIT 1
                    """),
                    {"name": r[0]},
                )).fetchone()
                result.append({
                    "client": r[0],
                    "nb_dossiers": r[1],
                    "ca_total_xof": round(r[2] or 0),
                    "reste_a_encaisser_xof": round(r[3] or 0),
                    "backlog_xof": round(r[4] or 0),
                    "premiere_commande": r[5][:10] if r[5] else None,
                    "derniere_commande": r[6][:10] if r[6] else None,
                    "secteur": client_row[0] if client_row else None,
                    "contact_email": client_row[1] if client_row else None,
                    "telephone": client_row[2] if client_row else None,
                    "dernier_projet": proj_row[0] if proj_row else None,
                })
        return result

    async def get_clients_by_country(self) -> list[dict]:
        """Répartition des clients par pays (le cockpit affiche le nb de clients)."""
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text("""
                SELECT COALESCE(NULLIF(country, ''), 'Autres/non renseigné') as pays,
                       COUNT(*) as nb_clients
                FROM clients GROUP BY pays ORDER BY nb_clients DESC
            """))).fetchall()
        # Regroupe le null avec les petits pays sous « Autres/non renseigné »
        top = [{"pays": r[0], "nb_clients": r[1]} for r in rows if r[0] != "Autres/non renseigné"][:4]
        autres = sum(r[1] for r in rows) - sum(t["nb_clients"] for t in top)
        if autres > 0:
            top.append({"pays": "Autres/non renseigné", "nb_clients": autres})
        return top

    async def get_monthly_revenue(self, year: int) -> list[dict]:
        """Série CA commandé par mois pour une année (graphe d'évolution du dashboard)."""
        from sqlalchemy import text
        sql = text("""
            SELECT strftime('%m', date_order) as mo,
                   SUM(amount) as ca,
                   COUNT(*) as nb
            FROM sale_orders
            WHERE state NOT IN ('cancel', 'draft')
              AND strftime('%Y', date_order) = :year
            GROUP BY mo ORDER BY mo
        """)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(sql, {"year": str(year)})).fetchall()
        return [
            {"mois": int(r[0]), "ca_xof": round(r[1] or 0), "nb_commandes": r[2]}
            for r in rows
        ]

    async def list_opportunities(self, stage: str | None = None, limit: int = 50) -> list[dict]:
        """Liste d'opportunités (kanban pipeline), triées par valeur pondérée décroissante."""
        from sqlalchemy import text
        sql = """
            SELECT name, client_name, stage, expected_revenue, probability,
                   salesperson_name, deadline, created_at
            FROM opportunities
            WHERE 1=1
        """
        params: dict = {"limit": limit}
        if stage:
            sql += " AND stage = :stage"
            params["stage"] = stage
        sql += " ORDER BY (expected_revenue * probability / 100) DESC LIMIT :limit"
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(text(sql), params)).fetchall()
        return [
            {
                "opportunite": r[0],
                "client": r[1],
                "stade": r[2],
                "revenu_attendu_xof": round(r[3] or 0),
                "probabilite_pct": round(r[4] or 0),
                "commercial": r[5] or "",
                "deadline": str(r[6]) if r[6] else None,
                "creee_le": str(r[7])[:10] if r[7] else None,
            }
            for r in rows
        ]

    @staticmethod
    def _client_to_domain(m: ClientModel) -> Client:
        return Client(
            client_id=m.client_id,
            name=m.name,
            sector=m.sector,
            solvency_score=m.solvency_score,
            odoo_id=m.odoo_id,
            contact_email=m.contact_email,
        )

    @staticmethod
    def _contract_to_domain(m: ContractModel) -> Contract:
        return Contract(
            contract_id=m.contract_id,
            client_id=m.client_id,
            title=m.title,
            value=m.value,
            currency=m.currency,
            start_date=m.start_date,
            end_date=m.end_date,
            status=ContractStatus(m.status),
            odoo_id=m.odoo_id,
        )

    @staticmethod
    def _invoice_to_domain(m: InvoiceModel) -> Invoice:
        return Invoice(
            invoice_id=m.invoice_id,
            client_id=m.client_id,
            amount=m.amount,
            currency=m.currency,
            due_date=m.due_date,
            status=InvoiceStatus(m.status),
            odoo_id=m.odoo_id,
            invoice_date=m.invoice_date,
            invoice_name=m.invoice_name,
            payment_date=m.payment_date,
        )

    @staticmethod
    def _project_to_domain(m: ProjectModel) -> Project:
        return Project(
            project_id=m.project_id,
            client_id=m.client_id,
            title=m.title,
            description=m.description,
            start_date=m.start_date,
            end_date=m.end_date,
            technologies=m.technologies or [],
            engineers=m.engineers or [],
            odoo_id=m.odoo_id,
        )
