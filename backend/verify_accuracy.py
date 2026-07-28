"""
Vérification croisée : Agent IA  vs  Odoo réel  vs  SQLite local
Pose les mêmes questions aux 3 sources et compare.
"""
import asyncio, httpx, json, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"
with open("tmp_token.txt", encoding="ascii") as f:
    TOKEN = f.read().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# ─── 1. Interroger l'agent via SSE ────────────────────────────────────────────
async def ask_agent(question: str) -> str:
    full = ""
    async with httpx.AsyncClient(timeout=90) as client:
        async with client.stream("POST", f"{BASE}/v1/chat/query",
            data={"text": question, "session_id": f"verify-{hash(question)}", "history": "[]"},
            headers=HEADERS) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"): continue
                p = line[5:].strip()
                if not p or p == "[DONE]": continue
                try:
                    e = json.loads(p)
                    if e.get("type") == "token":
                        full += e.get("content", "")
                except: pass
    return full.strip()

# ─── 2. Interroger Odoo directement ──────────────────────────────────────────
async def odoo_direct():
    """Récupère les données de référence depuis Odoo."""
    import sys; sys.path.insert(0, ".")
    from adapters.crm.odoo_adapter import OdooAdapter
    odoo = OdooAdapter()
    results = {}

    try:
        # CA avril 2026 (confirmés + livrés seulement)
        orders_apr = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2026-04-01"],
              ["date_order", "<=", "2026-04-30"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["name", "amount_total", "currency_id", "date_order"], "limit": 200})
        results["ca_avril_2026_nb_bdc"] = len(orders_apr)
        results["ca_avril_2026_xof"] = sum(o["amount_total"] for o in orders_apr)

        # CA mai 2026
        orders_may = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2026-05-01"],
              ["date_order", "<=", "2026-05-31"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["name", "amount_total", "currency_id"], "limit": 200})
        results["ca_mai_2026_nb_bdc"] = len(orders_may)
        results["ca_mai_2026_xof"] = sum(o["amount_total"] for o in orders_may)

        # Bon de commande spécifique FP/2026/12974
        bc = await odoo._call("sale.order", "search_read",
            [[["name", "=", "FP/2026/12974"]]],
            {"fields": ["name", "amount_total", "currency_id", "partner_id", "state"]})
        results["bc_fp_2026_12974"] = bc[0] if bc else None

        # Top 3 clients par CA en 2025
        orders_2025 = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2025-01-01"],
              ["date_order", "<=", "2025-12-31"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["partner_id", "amount_total"], "limit": 5000})
        by_client: dict = {}
        for o in orders_2025:
            cname = o["partner_id"][1] if o.get("partner_id") else "—"
            by_client[cname] = by_client.get(cname, 0) + o["amount_total"]
        top3 = sorted(by_client.items(), key=lambda x: x[1], reverse=True)[:3]
        results["top3_clients_2025"] = top3

        # Nombre total de clients actifs
        nb_clients = await odoo._call("res.partner", "search_count",
            [[["customer_rank", ">", 0], ["active", "=", True]]])
        results["nb_clients_total"] = nb_clients

    except Exception as e:
        results["odoo_error"] = str(e)
    finally:
        await odoo.close()

    return results

# ─── 3. Interroger SQLite directement ────────────────────────────────────────
async def sqlite_direct():
    from db.database import AsyncSessionLocal
    from sqlalchemy import text
    results = {}
    async with AsyncSessionLocal() as session:
        # CA avril 2026
        r = (await session.execute(text("""
            SELECT COUNT(*), SUM(amount) FROM sale_orders
            WHERE strftime('%Y-%m', date_order) = '2026-04'
            AND state NOT IN ('cancel', 'draft')"""))).fetchone()
        results["ca_avril_2026_nb_bdc"] = r[0]
        results["ca_avril_2026_xof"] = round(r[1] or 0)

        # CA mai 2026
        r = (await session.execute(text("""
            SELECT COUNT(*), SUM(amount) FROM sale_orders
            WHERE strftime('%Y-%m', date_order) = '2026-05'
            AND state NOT IN ('cancel', 'draft')"""))).fetchone()
        results["ca_mai_2026_nb_bdc"] = r[0]
        results["ca_mai_2026_xof"] = round(r[1] or 0)

        # BC spécifique
        r = (await session.execute(text("""
            SELECT name, amount, client_name, state FROM sale_orders
            WHERE name = 'FP/2026/12974' LIMIT 1"""))).fetchone()
        results["bc_fp_2026_12974"] = {"montant": round(r[1]) if r else None, "client": r[2] if r else None}

        # Top 3 clients 2025
        rows = (await session.execute(text("""
            SELECT client_name, SUM(amount) as ca FROM sale_orders
            WHERE strftime('%Y', date_order) = '2025'
            AND state NOT IN ('cancel', 'draft')
            GROUP BY client_id, client_name ORDER BY ca DESC LIMIT 3"""))).fetchall()
        results["top3_clients_2025"] = [(r[0], round(r[1])) for r in rows]

        # Nb clients
        r = (await session.execute(text("SELECT COUNT(*) FROM clients"))).fetchone()
        results["nb_clients_total"] = r[0]

    return results


# ─── Affichage comparatif ─────────────────────────────────────────────────────
def fmt_xof(v):
    if v is None: return "N/A"
    try: return f"{float(v):>18,.0f} XOF"
    except: return str(v)

def pct_diff(a, b):
    try:
        a, b = float(a), float(b)
        if b == 0: return "—"
        diff = abs(a - b) / b * 100
        symbol = "✅" if diff < 1 else ("⚠️" if diff < 5 else "❌")
        return f"{symbol} {diff:.1f}%"
    except: return "—"

async def main():
    print("\n" + "="*80)
    print("VÉRIFICATION CROISÉE : Agent IA  vs  SQLite local  vs  Odoo réel")
    print("="*80)

    # Récupérer les 3 sources en parallèle
    print("\n[1/3] Interrogation Odoo direct...")
    odoo = await odoo_direct()
    print("[2/3] Interrogation SQLite local...")
    sqlite = await sqlite_direct()
    print("[3/3] Interrogation Agent IA...")

    agent_questions = [
        "Quel est le CA total et le nombre de bons de commande confirmés en avril 2026 ?",
        "Quel est le CA total et le nombre de bons de commande confirmés en mai 2026 ?",
        "Quel est le montant exact du bon de commande FP/2026/12974 et pour quel client ?",
        "Quels sont les 3 meilleurs clients par CA en 2025 avec leurs montants ?",
        "Combien de clients avons-nous au total dans notre base ?",
    ]
    agent_answers = []
    for q in agent_questions:
        ans = await ask_agent(q)
        agent_answers.append(ans[:400])
        await asyncio.sleep(2)

    # ─── Affichage ───────────────────────────────────────────────────────────
    checks = [
        {
            "label": "CA Avril 2026 — Nb BDC",
            "odoo": odoo.get("ca_avril_2026_nb_bdc"),
            "sqlite": sqlite.get("ca_avril_2026_nb_bdc"),
        },
        {
            "label": "CA Avril 2026 — Montant XOF",
            "odoo": odoo.get("ca_avril_2026_xof"),
            "sqlite": sqlite.get("ca_avril_2026_xof"),
            "is_money": True,
        },
        {
            "label": "CA Mai 2026 — Nb BDC",
            "odoo": odoo.get("ca_mai_2026_nb_bdc"),
            "sqlite": sqlite.get("ca_mai_2026_nb_bdc"),
        },
        {
            "label": "CA Mai 2026 — Montant XOF",
            "odoo": odoo.get("ca_mai_2026_xof"),
            "sqlite": sqlite.get("ca_mai_2026_xof"),
            "is_money": True,
        },
    ]

    print("\n" + "─"*80)
    print(f"{'Indicateur':<35} {'Odoo réel':>22} {'SQLite local':>22} {'Écart':>10}")
    print("─"*80)

    for c in checks:
        o_val = c["odoo"]
        s_val = c["sqlite"]
        if c.get("is_money"):
            print(f"  {c['label']:<33} {fmt_xof(o_val):>22} {fmt_xof(s_val):>22}  {pct_diff(s_val, o_val):>10}")
        else:
            o_str = str(o_val) if o_val is not None else "N/A"
            s_str = str(s_val) if s_val is not None else "N/A"
            match = "✅" if str(o_val) == str(s_val) else "❌"
            print(f"  {c['label']:<33} {o_str:>22} {s_str:>22}  {match:>10}")

    print("\n" + "─"*80)
    print("FP/2026/12974 :")
    bc_odoo = odoo.get("bc_fp_2026_12974")
    bc_sqlite = sqlite.get("bc_fp_2026_12974")
    if bc_odoo:
        print(f"  Odoo   : {bc_odoo['partner_id'][1] if bc_odoo.get('partner_id') else '?'} — {fmt_xof(bc_odoo.get('amount_total'))}")
    print(f"  SQLite : {bc_sqlite.get('client') if bc_sqlite else 'N/A'} — {fmt_xof(bc_sqlite.get('montant') if bc_sqlite else None)}")

    print("\n" + "─"*80)
    print("Top 3 clients 2025 :")
    print("  Odoo   :", [(n[:35], fmt_xof(v)) for n, v in (odoo.get("top3_clients_2025") or [])])
    print("  SQLite :", [(n[:35], fmt_xof(v)) for n, v in (sqlite.get("top3_clients_2025") or [])])

    print("\n" + "─"*80)
    print(f"Nb clients total — Odoo: {odoo.get('nb_clients_total')} | SQLite: {sqlite.get('nb_clients_total')}")

    print("\n" + "="*80)
    print("RÉPONSES DE L'AGENT IA")
    print("="*80)
    for i, (q, a) in enumerate(zip(agent_questions, agent_answers)):
        print(f"\n[Q{i+1}] {q}")
        print(f"  → {a[:350].replace(chr(10), ' ')}")

    if odoo.get("odoo_error"):
        print(f"\n⚠️  Erreur Odoo : {odoo['odoo_error']}")

asyncio.run(main())
