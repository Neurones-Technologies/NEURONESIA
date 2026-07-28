# -*- coding: utf-8 -*-
"""
Test complexe — 15 questions stratégiques
Compare : AGENT IA  ↔  SQLite local  ↔  Odoo réel (pour les métriques clés)
"""
import sys, io, json, sqlite3, time, requests, asyncio, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"
DB   = "D:/Neurones-IA/data/local_db/neurones.db"

# ── Authentification ────────────────────────────────────────────────────────
def login():
    r = requests.post(f"{BASE}/v1/auth/login",
                      json={"email": "dtraore@neuronestech.com", "password": "1234"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

# ── Appel agent ─────────────────────────────────────────────────────────────
def ask(token, question, sid):
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    data = {"text": question, "session_id": sid, "history": "[]"}
    full = ""
    tools_called = []
    with requests.post(f"{BASE}/v1/chat/query", data=data, headers=headers,
                       stream=True, timeout=180) as resp:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "): continue
            d = raw[6:]
            if d == "[DONE]": break
            try:
                obj = json.loads(d)
                t = obj.get("type", "")
                if t in ("text", "token"):
                    full += obj.get("text", obj.get("content", ""))
                elif t == "tool_call":
                    tools_called.append(obj.get("name", "?"))
            except: pass
    return full.strip(), tools_called

# ── SQLite direct ───────────────────────────────────────────────────────────
def sql(q, p=()):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(q, p)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

def sql1(q, p=()):
    r = sql(q, p)
    return r[0] if r else {}

# ── Odoo direct (vérification ultime) ──────────────────────────────────────
sys.path.insert(0, "D:/Neurones-IA/backend")
os.chdir("D:/Neurones-IA/backend")

async def odoo_check(model, domain, fields, limit=1, agg=None):
    """Appel Odoo direct pour validation."""
    try:
        from adapters.crm.odoo_adapter import OdooAdapter
        odoo = OdooAdapter()
        records = await odoo._call(model, "search_read", [domain],
                                   {"fields": fields, "limit": limit})
        await odoo.close()
        return records
    except Exception as e:
        return [{"error": str(e)}]

def odoo_sync(model, domain, fields, limit=20):
    return asyncio.run(odoo_check(model, domain, fields, limit))

# ═══════════════════════════════════════════════════════════════════════════
# DÉFINITION DES 15 QUESTIONS
# ═══════════════════════════════════════════════════════════════════════════
questions = [
    # (num, session_id, question, catégorie)
    (1,  "cq01", "Quel est notre chiffre d'affaires total en 2025 sur les bons de commande confirmés ?",
     "CA annuel"),
    (2,  "cq02", "Quels sont nos 5 meilleurs clients par CA en 2025 ?",
     "Top clients"),
    (3,  "cq03", "Quel est notre délai moyen de recouvrement des factures en 2024 ?",
     "DSO"),
    (4,  "cq04", "Quels clients ont des factures impayées depuis plus de 90 jours ? Donne les montants.",
     "Risque impayés"),
    (5,  "cq05", "Quel est notre CA réalisé en USD et EUR en équivalent XOF sur l'historique complet ?",
     "Devises"),
    (6,  "cq06", "Quelle est notre marge commerciale globale sur l'ensemble des dossiers ?",
     "Marge globale"),
    (7,  "cq07", "Quels sont nos 5 dossiers les plus rentables en valeur absolue de marge ?",
     "Top dossiers"),
    (8,  "cq08", "Quel est notre CA réalisé au premier trimestre 2026 (janvier à mars) ?",
     "CA trimestriel"),
    (9,  "cq09", "Quels clients représentent le plus gros risque d'impayés (factures en retard > 30 jours) ?",
     "Risque client"),
    (10, "cq10", "Quel est le CA total généré par les clients Orange (tous pays confondus) depuis le début ?",
     "CA groupe client"),
    (11, "cq11", "Combien avons-nous payé à nos fournisseurs et combien reste-t-il à payer sur les dossiers ?",
     "Fournisseurs"),
    (12, "cq12", "Quels sont nos 3 meilleurs commerciaux par CA en 2025 ?",
     "Performance commerciaux"),
    (13, "cq13", "Quelle est la valeur pondérée de notre pipeline commercial actuel ?",
     "Pipeline"),
    (14, "cq14", "Pour les dossiers créés en 2025 : quel est le CA, la marge, ce qu'on a encaissé et ce qui reste ?",
     "Dossiers 2025"),
    (15, "cq15", "Quel est l'historique complet de notre relation commerciale avec MTN CI ?",
     "Historique client"),
]

# ── Références SQLite ──────────────────────────────────────────────────────
refs_sqlite = {
    1:  sql1("SELECT ROUND(SUM(amount)/1e9,3) ca, COUNT(*) n FROM sale_orders WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done')"),
    2:  sql("SELECT client_name, ROUND(SUM(amount)/1e6) ca FROM sale_orders WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done') GROUP BY client_name ORDER BY SUM(amount) DESC LIMIT 5"),
    3:  sql1("SELECT COUNT(*) n, ROUND(AVG(julianday(payment_date)-julianday(invoice_date)),1) dso FROM invoices WHERE payment_date IS NOT NULL AND status='paid' AND strftime('%Y',invoice_date)='2024'"),
    4:  sql1("SELECT COUNT(*) n, ROUND(SUM(amount)/1e6,1) total_M FROM invoices WHERE status='unpaid' AND julianday('now')-julianday(due_date)>90"),
    5:  sql("SELECT currency, ROUND(SUM(amount)/1e9,3) ca_Mds, COUNT(*) n FROM sale_orders WHERE state IN('sale','done') AND currency!='XOF' GROUP BY currency"),
    6:  sql1("SELECT ROUND(SUM(ca_provisoire)/1e9,3) ca, ROUND(SUM(marge_provisoire)/1e9,3) marge, ROUND(AVG(perc_marge_provisoire),1) pct, COUNT(*) n FROM dossiers"),
    7:  sql("SELECT dossier_ref, client_name, ROUND(marge_provisoire/1e6) mg, ROUND(perc_marge_provisoire,1) pct FROM dossiers ORDER BY marge_provisoire DESC LIMIT 5"),
    8:  sql1("SELECT ROUND(SUM(amount)/1e9,3) ca, COUNT(*) n FROM sale_orders WHERE strftime('%Y-%m',date_order) BETWEEN '2026-01' AND '2026-03' AND state IN('sale','done')"),
    9:  sql("SELECT c.name client, ROUND(SUM(i.amount)/1e6,1) M, COUNT(*) n FROM invoices i JOIN clients c ON i.client_id=c.client_id WHERE i.status='unpaid' AND julianday('now')-julianday(i.due_date)>30 GROUP BY c.name ORDER BY SUM(i.amount) DESC LIMIT 5"),
    10: sql1("SELECT ROUND(SUM(amount)/1e9,3) ca, COUNT(*) n FROM sale_orders WHERE lower(client_name) LIKE '%orange%' AND state IN('sale','done')"),
    11: sql1("SELECT ROUND(SUM(fournisseurs_payes)/1e9,3) payes, ROUND(SUM(fournisseurs_restant)/1e9,3) restant FROM dossiers"),
    12: sql("SELECT salesperson_name, ROUND(SUM(amount)/1e6) ca, COUNT(*) n FROM sale_orders WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done') AND salesperson_name!='' GROUP BY salesperson_name ORDER BY SUM(amount) DESC LIMIT 3"),
    13: sql1("SELECT COUNT(*) n, ROUND(SUM(expected_revenue*probability/100)/1e6,1) weighted_M FROM opportunities"),
    14: sql1("SELECT ROUND(SUM(ca_provisoire)/1e9,3) ca, ROUND(SUM(marge_provisoire)/1e9,3) marge, ROUND(SUM(montant_recu)/1e9,3) encaisse, ROUND(SUM(reste_a_encaisser)/1e9,3) reste FROM dossiers WHERE strftime('%Y',date_creation)='2025'"),
    15: sql1("SELECT ROUND(SUM(amount)/1e6) ca_M, COUNT(*) n, MIN(strftime('%Y',date_order)) debut FROM sale_orders WHERE lower(client_name) LIKE '%mtn%' AND state IN('sale','done')"),
}

# ═══════════════════════════════════════════════════════════════════════════
# EXÉCUTION DES TESTS
# ═══════════════════════════════════════════════════════════════════════════
tok = login()
print(f"Token OK — {len(questions)} questions complexes\n")
print("=" * 70)

scores = {"ok": 0, "partiel": 0, "ko": 0}
results = []

for (num, sid, question, cat) in questions:
    print(f"\n{'═'*70}")
    print(f"Q{num:02d} [{cat}]")
    print(f"  {question}")
    print("-" * 70)

    # Délai entre questions pour éviter l'overload API
    if num > 1:
        time.sleep(8)

    t0 = time.time()
    rep, tools = ask(tok, question, sid)
    # Retry une fois si overloaded
    if "overloaded_error" in rep or "Overloaded" in rep:
        print("  [API surchargée — retry dans 20s]")
        time.sleep(20)
        rep, tools = ask(tok, question, sid)
    elapsed = time.time() - t0

    print(f"\n[IA — {elapsed:.1f}s — outils: {', '.join(tools) or 'aucun'}]")
    print(rep or "(vide)")

    ref = refs_sqlite[num]
    print(f"\n[REF SQLITE]")
    if isinstance(ref, list):
        for r in ref:
            print(f"  {r}")
    else:
        print(f"  {ref}")

    results.append({
        "num": num, "cat": cat, "elapsed": elapsed,
        "tools": tools, "rep_len": len(rep), "rep": rep[:300]
    })

print(f"\n\n{'═'*70}")
print("SYNTHÈSE FINALE")
print(f"{'═'*70}")
for r in results:
    status = "✓" if r["rep_len"] > 50 else "?"
    print(f"  Q{r['num']:02d} [{r['cat']:<25}] {status} {r['elapsed']:.1f}s  outils={r['tools']}")
print(f"\nFIN DU TEST COMPLEXE")
