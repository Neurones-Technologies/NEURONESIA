# -*- coding: utf-8 -*-
"""10 nouvelles questions pour valider brievete + exactitude."""
import sys, io, json, sqlite3, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"
DB   = "D:/Neurones-IA/data/local_db/neurones.db"

def login():
    r = requests.post(f"{BASE}/v1/auth/login",
                      json={"email": "dtraore@neuronestech.com", "password": "1234"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

def ask(token, question, sid):
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    data = {"text": question, "session_id": sid, "history": "[]"}
    full = ""
    with requests.post(f"{BASE}/v1/chat/query", data=data, headers=headers,
                       stream=True, timeout=90) as resp:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "): continue
            d = raw[6:]
            if d == "[DONE]": break
            try:
                obj = json.loads(d)
                t = obj.get("type", "")
                if t in ("text", "token"):
                    full += obj.get("text", obj.get("content", ""))
            except: pass
    return full.strip()

def sql(q, p=()):
    conn = sqlite3.connect(DB)
    cur = conn.cursor(); cur.execute(q, p)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

def sep(n, q):
    print(f"\n{'='*65}")
    print(f"Q{n}: {q}")
    print("-"*65)

# ── REFERENCE DATA ────────────────────────────────────────────────────
refs = {
    1: sql("SELECT SUM(amount) ca, COUNT(*) nb FROM sale_orders WHERE strftime('%Y',date_order)='2026' AND state IN('sale','done')"),
    2: sql("SELECT SUM(amount) ca, COUNT(*) nb FROM sale_orders WHERE strftime('%Y-%m',date_order)='2026-04' AND state IN('sale','done')"),
    3: sql("SELECT COUNT(DISTINCT client_id) n FROM sale_orders WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done')"),
    4: sql("""SELECT strftime('%Y-%m',date_order) mois, SUM(amount) ca, COUNT(*) nb
              FROM sale_orders WHERE state IN('sale','done') AND date_order >= '2026-01-01'
              GROUP BY mois ORDER BY mois"""),
    5: sql("""SELECT client_name, SUM(amount) ca FROM sale_orders
              WHERE strftime('%Y',date_order)='2026' AND state IN('sale','done')
              GROUP BY client_name ORDER BY ca DESC LIMIT 3"""),
    6: sql("""SELECT COUNT(*) n, SUM(amount) total FROM invoices
              WHERE status NOT IN('paid','cancel') AND due_date < date('now')"""),
    7: sql("""SELECT client_name, SUM(amount) ca FROM sale_orders
              WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done')
              AND lower(client_name) LIKE '%orange%'
              GROUP BY client_name ORDER BY ca DESC"""),
    8: sql("""WITH ca24 AS (SELECT client_name, SUM(amount) ca FROM sale_orders
                WHERE strftime('%Y',date_order)='2024' AND state IN('sale','done') GROUP BY client_name),
              ca25 AS (SELECT client_name, SUM(amount) ca FROM sale_orders
                WHERE strftime('%Y',date_order)='2025' AND state IN('sale','done') GROUP BY client_name)
              SELECT COUNT(*) n FROM ca24 a JOIN ca25 b ON a.client_name=b.client_name WHERE b.ca < a.ca"""),
    9: sql("""SELECT json_extract(j.value,'$.product') prod, SUM(json_extract(j.value,'$.subtotal')) ca,
              COUNT(DISTINCT o.order_id) nb
              FROM sale_orders o, json_each(o.order_lines) j
              WHERE strftime('%Y',o.date_order)='2025' AND o.state IN('sale','done')
              GROUP BY prod ORDER BY ca DESC LIMIT 5"""),
    10: sql("""SELECT COUNT(DISTINCT strftime('%Y',date_order)) n_annees,
               MIN(strftime('%Y',date_order)) debut, MAX(strftime('%Y',date_order)) fin
               FROM sale_orders WHERE client_name='MTN CI' AND state IN('sale','done')"""),
}

questions = [
    (1,  "CA total confirme 2026 ?"),
    (2,  "CA du mois d'avril 2026 ?"),
    (3,  "Combien de clients ont commande en 2025 ?"),
    (4,  "CA mois par mois depuis janvier 2026 ?"),
    (5,  "Top 3 clients par CA en 2026 ?"),
    (6,  "Combien de factures sont en retard de paiement et pour quel montant total ?"),
    (7,  "Quel est le CA total realise avec les clients Orange en 2025 ?"),
    (8,  "Combien de clients ont baisse leur CA entre 2024 et 2025 ?"),
    (9,  "Top 5 produits par CA en 2025 ?"),
    (10, "Depuis combien d annees MTN CI est client chez nous ?"),
]

tok = login()
print("Token OK — 10 questions\n")

for (ref_n, q) in questions:
    sep(ref_n, q)
    t0 = time.time()
    rep = ask(tok, q, f"q10_{ref_n}")
    elapsed = time.time() - t0
    nb_chars = len(rep)
    print(f"[AGENT — {elapsed:.1f}s — {nb_chars} caracteres]")
    print(rep or "(vide)")

    ref = refs[ref_n]
    print(f"\n[REF SQLITE]")
    if ref_n == 1:
        print(f"  CA 2026 = {ref[0]['ca']/1e9:.3f} Mds XOF — {ref[0]['nb']} BDC")
    elif ref_n == 2:
        print(f"  CA avril 2026 = {ref[0]['ca']/1e6:.0f} M XOF — {ref[0]['nb']} BDC")
    elif ref_n == 3:
        print(f"  {ref[0]['n']} clients actifs en 2025")
    elif ref_n == 4:
        for r in ref: print(f"  {r['mois']} : {r['ca']/1e6:.0f} M XOF ({r['nb']} BDC)")
    elif ref_n == 5:
        for r in ref: print(f"  {r['client_name'][:40]} : {r['ca']/1e6:.0f} M XOF")
    elif ref_n == 6:
        print(f"  {ref[0]['n']} factures en retard — {ref[0]['total']/1e9:.2f} Mds XOF")
    elif ref_n == 7:
        for r in ref: print(f"  {r['client_name'][:40]} : {r['ca']/1e6:.0f} M XOF")
        print(f"  TOTAL : {sum(r['ca'] for r in ref)/1e6:.0f} M XOF")
    elif ref_n == 8:
        print(f"  {ref[0]['n']} clients en baisse CA 2024->2025")
    elif ref_n == 9:
        for r in ref: print(f"  {(r['prod'] or 'N/A')[:45]} : {r['ca']/1e6:.0f} M XOF ({r['nb']} BDC)")
    elif ref_n == 10:
        r = ref[0]
        print(f"  {r['n_annees']} annees ({r['debut']} -> {r['fin']})")

print("\n\nFIN DU TEST")
