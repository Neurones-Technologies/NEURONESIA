# -*- coding: utf-8 -*-
"""
Récupère les vraies valeurs Odoo pour les 15 questions du test complexe.
Connexion directe via OdooAdapter.
"""
import sys, io, asyncio, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, "D:/Neurones-IA/backend")
os.chdir("D:/Neurones-IA/backend")

async def main():
    from adapters.crm.odoo_adapter import OdooAdapter
    odoo = OdooAdapter()

    print("Connexion Odoo en cours...\n")

    # ── Q1 : CA 2025 sur BDC confirmés ─────────────────────────────────────────
    print("=== Q1 : CA 2025 BDC confirmés ===")
    bdc_2025 = await odoo._call("sale.order", "search_read",
        [[["state", "in", ["sale", "done"]],
          ["date_order", ">=", "2025-01-01"],
          ["date_order", "<=", "2025-12-31"]]],
        {"fields": ["name", "amount_total", "currency_id"], "limit": 0})
    ca_xof = sum(o.get("amount_total", 0) for o in bdc_2025)
    print(f"  BDC confirmés 2025 : {len(bdc_2025)} commandes")
    print(f"  CA total (sans conversion) : {ca_xof/1e9:.3f} Mds")

    # ── Q2 : Top 5 clients CA 2025 ─────────────────────────────────────────────
    print("\n=== Q2 : Top 5 clients CA 2025 ===")
    from collections import defaultdict
    by_client = defaultdict(float)
    for o in bdc_2025:
        partner = o.get("partner_id") or [None, "?"]
        name = partner[1] if len(partner) > 1 else "?"
        by_client[name] += o.get("amount_total", 0)
    top5 = sorted(by_client.items(), key=lambda x: -x[1])[:5]
    for name, amt in top5:
        print(f"  {name} : {amt/1e6:.0f} M XOF")

    # ── Q3 : DSO 2024 ──────────────────────────────────────────────────────────
    print("\n=== Q3 : DSO moyen 2024 ===")
    # Factures client payées en 2024
    inv_paid = await odoo._call("account.move", "search_read",
        [[["move_type", "=", "out_invoice"],
          ["payment_state", "in", ["paid", "in_payment"]],
          ["invoice_date", ">=", "2024-01-01"],
          ["invoice_date", "<=", "2024-12-31"]]],
        {"fields": ["id", "invoice_date", "invoice_date_due", "invoice_payments_widget"], "limit": 5000})
    dso_vals = []
    from datetime import datetime
    for inv in inv_paid:
        inv_date_raw = inv.get("invoice_date")
        widget = inv.get("invoice_payments_widget")
        if not widget or isinstance(widget, bool):
            continue
        content = widget.get("content") if isinstance(widget, dict) else []
        for entry in (content or []):
            pay_date_raw = entry.get("date")
            if not pay_date_raw or not inv_date_raw:
                continue
            try:
                inv_dt = datetime.strptime(str(inv_date_raw)[:10], "%Y-%m-%d")
                pay_dt = datetime.strptime(str(pay_date_raw)[:10], "%Y-%m-%d")
                delta = (pay_dt - inv_dt).days
                if 0 <= delta < 3650:
                    dso_vals.append(delta)
            except ValueError:
                pass
    if dso_vals:
        print(f"  Factures avec date paiement : {len(dso_vals)}")
        print(f"  DSO moyen 2024 : {sum(dso_vals)/len(dso_vals):.1f} jours")
    else:
        print("  Aucune date de paiement trouvée")

    # ── Q4 : Factures impayées > 90 jours ──────────────────────────────────────
    print("\n=== Q4 : Factures impayées > 90 jours ===")
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    inv_unpaid = await odoo._call("account.move", "search_read",
        [[["move_type", "=", "out_invoice"],
          ["payment_state", "in", ["not_paid", "partial"]],
          ["invoice_date_due", "<=", cutoff]]],
        {"fields": ["partner_id", "amount_residual", "invoice_date_due"], "limit": 0})
    total_unpaid = sum(i.get("amount_residual", 0) for i in inv_unpaid)
    by_client_unpaid = defaultdict(float)
    for i in inv_unpaid:
        p = i.get("partner_id") or [None, "?"]
        name = p[1] if len(p) > 1 else "?"
        by_client_unpaid[name] += i.get("amount_residual", 0)
    top10_unpaid = sorted(by_client_unpaid.items(), key=lambda x: -x[1])[:10]
    print(f"  Total factures impayées > 90j : {len(inv_unpaid)}")
    print(f"  Montant total : {total_unpaid/1e9:.3f} Mds XOF")
    for name, amt in top10_unpaid:
        print(f"    {name} : {amt/1e6:.0f} M XOF")

    # ── Q5 : CA par devise (historique) ────────────────────────────────────────
    print("\n=== Q5 : CA par devise (historique) ===")
    bdc_all = await odoo._call("sale.order", "search_read",
        [[["state", "in", ["sale", "done"]]]],
        {"fields": ["amount_total", "currency_id"], "limit": 0})
    by_currency = defaultdict(lambda: {"total": 0, "n": 0})
    for o in bdc_all:
        curr_field = o.get("currency_id") or [None, "XOF"]
        curr = curr_field[1] if len(curr_field) > 1 else "XOF"
        by_currency[curr]["total"] += o.get("amount_total", 0)
        by_currency[curr]["n"] += 1
    for curr, data in sorted(by_currency.items(), key=lambda x: -x[1]["total"]):
        print(f"  {curr} : {data['total']/1e9:.3f} Mds | {data['n']} BDC")

    # ── Q8 : CA Q1 2026 ────────────────────────────────────────────────────────
    print("\n=== Q8 : CA Q1 2026 (jan-mar) ===")
    bdc_q1_2026 = await odoo._call("sale.order", "search_read",
        [[["state", "in", ["sale", "done"]],
          ["date_order", ">=", "2026-01-01"],
          ["date_order", "<=", "2026-03-31"]]],
        {"fields": ["amount_total", "currency_id"], "limit": 0})
    ca_q1 = sum(o.get("amount_total", 0) for o in bdc_q1_2026)
    print(f"  BDC Q1 2026 : {len(bdc_q1_2026)} commandes")
    print(f"  CA Q1 2026 : {ca_q1/1e9:.3f} Mds XOF")

    # ── Q10 : CA Orange total ───────────────────────────────────────────────────
    print("\n=== Q10 : CA groupe Orange (tous pays) ===")
    # Chercher les partners contenant "orange"
    orange_partners = await odoo._call("res.partner", "search_read",
        [[["name", "ilike", "orange"]]],
        {"fields": ["id", "name"], "limit": 0})
    orange_ids = [p["id"] for p in orange_partners]
    print(f"  Partenaires Orange trouvés : {len(orange_ids)}")
    if orange_ids:
        bdc_orange = await odoo._call("sale.order", "search_read",
            [[["state", "in", ["sale", "done"]],
              ["partner_id", "in", orange_ids]]],
            {"fields": ["amount_total", "partner_id"], "limit": 0})
        ca_orange = sum(o.get("amount_total", 0) for o in bdc_orange)
        print(f"  BDC Orange total : {len(bdc_orange)} commandes")
        print(f"  CA Orange : {ca_orange/1e9:.3f} Mds XOF")

    # ── Q12 : Top 3 commerciaux 2025 ───────────────────────────────────────────
    print("\n=== Q12 : Top 3 commerciaux CA 2025 ===")
    bdc_2025_sales = await odoo._call("sale.order", "search_read",
        [[["state", "in", ["sale", "done"]],
          ["date_order", ">=", "2025-01-01"],
          ["date_order", "<=", "2025-12-31"]]],
        {"fields": ["amount_total", "user_id"], "limit": 0})
    by_salesperson = defaultdict(float)
    for o in bdc_2025_sales:
        user = o.get("user_id") or [None, "Inconnu"]
        name = user[1] if len(user) > 1 else "Inconnu"
        by_salesperson[name] += o.get("amount_total", 0)
    top3 = sorted(by_salesperson.items(), key=lambda x: -x[1])[:3]
    for name, amt in top3:
        print(f"  {name} : {amt/1e6:.0f} M XOF")

    # ── Q13 : Pipeline pondéré ─────────────────────────────────────────────────
    print("\n=== Q13 : Pipeline commercial (CRM) ===")
    opps = await odoo._call("crm.lead", "search_read",
        [[["type", "=", "opportunity"]]],
        {"fields": ["expected_revenue", "probability"], "limit": 10000})
    total_opps = len(opps)
    weighted = sum(o.get("expected_revenue", 0) * o.get("probability", 0) / 100 for o in opps)
    print(f"  Total opportunities : {total_opps}")
    print(f"  Pipeline pondéré : {weighted/1e6:.1f} M XOF")
    # Si paginé (> 10000 opps)
    if total_opps == 10000:
        print("  WARNING: peut-être tronqué à 10000 — paginer si nécessaire")

    # ── Q15 : Historique MTN CI ─────────────────────────────────────────────────
    print("\n=== Q15 : Historique MTN CI ===")
    mtn_partners = await odoo._call("res.partner", "search_read",
        [[["name", "ilike", "mtn ci"]]],
        {"fields": ["id", "name"], "limit": 10})
    mtn_ids = [p["id"] for p in mtn_partners]
    print(f"  Partenaires MTN CI : {[(p['id'], p['name']) for p in mtn_partners]}")
    if mtn_ids:
        bdc_mtn = await odoo._call("sale.order", "search_read",
            [[["state", "in", ["sale", "done"]],
              ["partner_id", "in", mtn_ids]]],
            {"fields": ["amount_total", "date_order"], "limit": 0})
        ca_mtn = sum(o.get("amount_total", 0) for o in bdc_mtn)
        dates = [o.get("date_order") for o in bdc_mtn if o.get("date_order")]
        debut = min(dates)[:4] if dates else "N/A"
        print(f"  BDC MTN CI : {len(bdc_mtn)} commandes depuis {debut}")
        print(f"  CA total : {ca_mtn/1e6:.0f} M XOF")

    await odoo.close()
    print("\n=== FIN ODOO ===")

asyncio.run(main())
