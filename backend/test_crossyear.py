"""Test cross-year query to validate fix."""
import asyncio
import httpx
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


BASE = "http://localhost:8000"


async def login() -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{BASE}/v1/auth/login", json={"email": "dtraore@neuronestech.com", "password": "1234"})
        r.raise_for_status()
        return r.json()["access_token"]


async def ask(token: str, question: str, session_id: str = "test") -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {"text": question, "session_id": session_id, "history": []}
    full = ""
    async with httpx.AsyncClient(timeout=120) as c:
        async with c.stream("POST", f"{BASE}/v1/chat/query", json=payload, headers=headers) as resp:
            print(f"  [SSE HTTP {resp.status_code}]", flush=True)
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
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
                            print(f"  [RESULT] {str(obj.get('content', ''))[:80]}", flush=True)
                    except Exception as e:
                        print(f"  [PARSE ERR] {e}: {line[:60]}", flush=True)
    return full


async def direct_sqlite(question_sql: str) -> list:
    import sqlite3
    conn = sqlite3.connect("D:/Neurones-IA/data/local_db/neurones.db")
    cur = conn.cursor()
    cur.execute(question_sql)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


async def main():
    print("Obtention du token...")
    token = await login()
    print("Token OK\n")

    # Q1 — cross-year growth
    q1 = (
        "Parmi les clients qui ont commandé en 2024 ET en 2025, "
        "combien ont augmenté leur CA de plus de 20% ? Donne la liste."
    )
    print(f"{'='*65}")
    print(f"Q1: {q1}")
    print("-" * 65)
    rep1 = await ask(token, q1, "cx_1")
    print(rep1)

    # Référence SQLite directe
    sql = """
    WITH ca24 AS (
        SELECT client_name, SUM(amount) ca
        FROM sale_orders
        WHERE strftime('%Y', date_order) = '2024'
          AND state IN ('sale', 'done')
        GROUP BY client_name
    ),
    ca25 AS (
        SELECT client_name, SUM(amount) ca
        FROM sale_orders
        WHERE strftime('%Y', date_order) = '2025'
          AND state IN ('sale', 'done')
        GROUP BY client_name
    )
    SELECT a.client_name, ROUND(a.ca) ca2024, ROUND(b.ca) ca2025,
           ROUND((b.ca - a.ca) / a.ca * 100, 1) pct_growth
    FROM ca24 a JOIN ca25 b ON a.client_name = b.client_name
    WHERE b.ca > a.ca * 1.2
    ORDER BY pct_growth DESC
    """
    rows = await direct_sqlite(sql)
    print(f"\n[REFERENCE SQLITE] {len(rows)} clients avec hausse >20% en 2024 -> 2025")
    for r in rows[:10]:
        print(f"  {r['client_name'][:40]:<40} {r['pct_growth']:>6}%  ({r['ca2024']/1e6:.0f}M -> {r['ca2025']/1e6:.0f}M XOF)")
    if len(rows) > 10:
        print(f"  ... et {len(rows)-10} autres")

    # Q2 — CA 2025
    print(f"\n{'='*65}")
    q2 = "Quel est notre chiffre d'affaires total confirmé en 2025 ?"
    print(f"Q2: {q2}")
    print("-" * 65)
    rep2 = await ask(token, q2, "cx_2")
    print(rep2)

    rows2 = await direct_sqlite(
        "SELECT SUM(amount) ca, COUNT(*) nb FROM sale_orders "
        "WHERE strftime('%Y', date_order)='2025' AND state IN ('sale','done')"
    )
    print(f"\n[RÉFÉRENCE SQLITE] CA 2025 = {rows2[0]['ca']/1e9:.3f} Mds XOF — {rows2[0]['nb']} BDC")


asyncio.run(main())
