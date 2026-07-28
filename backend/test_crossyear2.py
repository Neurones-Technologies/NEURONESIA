# -*- coding: utf-8 -*-
"""Test cross-year query — synchronous avec requests."""
import sys, io, json, sqlite3, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests

BASE = "http://localhost:8000"
DB   = "D:/Neurones-IA/data/local_db/neurones.db"


def login():
    r = requests.post(f"{BASE}/v1/auth/login",
                      json={"email": "dtraore@neuronestech.com", "password": "1234"},
                      timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def ask_sse(token, question, session_id="cx"):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
    }
    # endpoint attend FormData (support pièces jointes)
    data = {"text": question, "session_id": session_id, "history": "[]"}
    full = ""
    with requests.post(f"{BASE}/v1/chat/query", data=data, headers=headers,
                       stream=True, timeout=120) as resp:
        print(f"  [HTTP {resp.status_code}]", flush=True)
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if raw_line.startswith("data: "):
                data = raw_line[6:]
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    t = obj.get("type", "")
                    if t in ("text", "token"):
                        chunk = obj.get("text", obj.get("content", ""))
                        full += chunk
                    elif t == "tool_call":
                        print(f"  [TOOL] {obj.get('name', '?')}", flush=True)
                    elif t == "tool_result":
                        snip = str(obj.get("content", ""))[:100]
                        print(f"  [TOOL RESULT] {snip}", flush=True)
                except Exception as e:
                    print(f"  [PARSE ERR] {e}: {raw_line[:80]}", flush=True)
    return full


def sql(query, params=()):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def sep(title=""):
    print(f"\n{'='*65}")
    if title:
        print(f"  {title}")
        print("-" * 65)


# ─── MAIN ──────────────────────────────────────────────────────────────
print("Login...")
tok = login()
print("OK\n")

# ── Q1 — Cross-year growth ─────────────────────────────────────────────
sep("Q1: Clients 2024+2025 avec hausse CA >20%")
q1 = ("Parmi les clients qui ont commande en 2024 ET en 2025, "
      "combien ont augmente leur CA de plus de 20% ? Donne-moi la liste.")
rep1 = ask_sse(tok, q1, "cx_q1")
print("\n[AGENT REPOND]:")
print(rep1 or "(vide)")

ref1 = sql("""
    WITH ca24 AS (
        SELECT client_name, SUM(amount) ca
        FROM sale_orders
        WHERE strftime('%Y', date_order) = '2024' AND state IN ('sale','done')
        GROUP BY client_name
    ),
    ca25 AS (
        SELECT client_name, SUM(amount) ca
        FROM sale_orders
        WHERE strftime('%Y', date_order) = '2025' AND state IN ('sale','done')
        GROUP BY client_name
    )
    SELECT a.client_name, ROUND(a.ca) ca2024, ROUND(b.ca) ca2025,
           ROUND((b.ca - a.ca) / a.ca * 100, 1) pct_growth
    FROM ca24 a JOIN ca25 b ON a.client_name = b.client_name
    WHERE b.ca > a.ca * 1.2
    ORDER BY pct_growth DESC
""")
print(f"\n[REFERENCE SQLITE] {len(ref1)} clients avec hausse >20%:")
for r in ref1[:15]:
    print(f"  {r['client_name'][:42]:<42} {r['pct_growth']:>6}%  "
          f"({r['ca2024']/1e6:.0f}M -> {r['ca2025']/1e6:.0f}M XOF)")
if len(ref1) > 15:
    print(f"  ... +{len(ref1)-15} autres")

# ── Q2 — CA 2025 ──────────────────────────────────────────────────────
sep("Q2: Chiffre d'affaires total 2025")
q2 = "Quel est notre chiffre d'affaires total confirme en 2025 ?"
rep2 = ask_sse(tok, q2, "cx_q2")
print("\n[AGENT REPOND]:")
print(rep2 or "(vide)")

ref2 = sql(
    "SELECT SUM(amount) ca, COUNT(*) nb FROM sale_orders "
    "WHERE strftime('%Y', date_order)='2025' AND state IN ('sale','done')"
)
print(f"\n[REFERENCE SQLITE] CA 2025 = {ref2[0]['ca']/1e9:.3f} Mds XOF — {ref2[0]['nb']} BDC")

# ── Q3 — Clients avec top CA 2025 ─────────────────────────────────────
sep("Q3: Top 5 clients CA 2025")
q3 = "Quels sont les 5 meilleurs clients en chiffre d'affaires en 2025 ?"
rep3 = ask_sse(tok, q3, "cx_q3")
print("\n[AGENT REPOND]:")
print(rep3 or "(vide)")

ref3 = sql("""
    SELECT client_name, SUM(amount) ca, COUNT(*) nb
    FROM sale_orders
    WHERE strftime('%Y', date_order)='2025' AND state IN ('sale','done')
    GROUP BY client_name ORDER BY ca DESC LIMIT 5
""")
print("\n[REFERENCE SQLITE] Top 5 clients 2025:")
for r in ref3:
    print(f"  {r['client_name'][:45]:<45} {r['ca']/1e6:>8.0f} M XOF  ({r['nb']} BDC)")

print("\nDone.")
