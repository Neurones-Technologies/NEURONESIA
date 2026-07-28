"""Sync ciblée : invoice_date, invoice_name, payment_date pour les factures existantes."""
import asyncio
import sys
sys.path.insert(0, ".")

async def main():
    from adapters.crm.odoo_adapter import OdooAdapter
    from db.database import AsyncSessionLocal
    from db.models import InvoiceModel
    from sqlalchemy import select

    odoo = OdooAdapter()

    print("1. Récupération des factures depuis Odoo (invoice_date + invoice_name)...")
    invoices = await odoo.get_all_invoices(limit=5000)
    print(f"   {len(invoices)} factures récupérées")

    async with AsyncSessionLocal() as session:
        updated = 0
        for inv in invoices:
            row = await session.get(InvoiceModel, inv.invoice_id)
            if row:
                changed = False
                if inv.invoice_date and row.invoice_date is None:
                    row.invoice_date = inv.invoice_date
                    changed = True
                if inv.invoice_name and row.invoice_name is None:
                    row.invoice_name = inv.invoice_name
                    changed = True
                if changed:
                    updated += 1
        await session.commit()
        print(f"   {updated} factures mises à jour (invoice_date / invoice_name)")

    print("2. Récupération des dates de paiement (account.payment)...")
    payment_dates = await odoo.get_payment_dates()
    print(f"   {len(payment_dates)} paiements récupérés")

    async with AsyncSessionLocal() as session:
        updated_pay = 0
        for odoo_id_str, pay_date in payment_dates.items():
            result = await session.execute(
                select(InvoiceModel).where(InvoiceModel.odoo_id == int(odoo_id_str))
            )
            row = result.scalar_one_or_none()
            if row and row.payment_date != pay_date:
                row.payment_date = pay_date
                updated_pay += 1
        await session.commit()
        print(f"   {updated_pay} factures avec date de paiement mise à jour")

    await odoo.close()

    # Vérification MTN CI
    print("\n3. Vérification MTN CI...")
    import sqlite3
    conn = sqlite3.connect("D:/Neurones-IA/data/local_db/neurones.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT i.invoice_name, i.invoice_date, i.due_date, i.payment_date, i.status, i.amount
        FROM invoices i JOIN clients c ON c.client_id = i.client_id
        WHERE c.name LIKE '%MTN%'
          AND i.invoice_date IS NOT NULL
          AND substr(i.invoice_date, 1, 4) = '2025'
        ORDER BY i.invoice_date
        LIMIT 10
    """)
    rows = cur.fetchall()
    print(f"   {len(rows)} factures MTN CI 2025 avec invoice_date:")
    for r in rows:
        inv_name, inv_date, due_date, pay_date, status, amount = r
        delai = ""
        if inv_date and pay_date:
            from datetime import datetime as dt
            d1 = dt.strptime(str(inv_date)[:10], "%Y-%m-%d")
            d2 = dt.strptime(str(pay_date)[:10], "%Y-%m-%d")
            delai = f" → {(d2-d1).days}j de recouvrement"
        print(f"   {inv_name} | émis: {str(inv_date)[:10]} | éch: {str(due_date)[:10]} | payé: {str(pay_date)[:10] if pay_date else 'N/A'} | {status}{delai}")
    conn.close()

asyncio.run(main())
