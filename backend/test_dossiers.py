# -*- coding: utf-8 -*-
"""Test profond — dossiers, marges, rentabilite."""
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
                       stream=True, timeout=120) as resp:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "): continue
            d = raw[6:]
            if d == "[DONE]": break
            try:
                obj = json.loads(d)
                t = obj.get("type","")
                if t in ("text","token"):
                    full += obj.get("text", obj.get("content",""))
                elif t == "tool_call":
                    print(f"  [TOOL] {obj.get('name','?')}", flush=True)
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

# ── RÉFÉRENCES DIRECTES SQLITE ─────────────────────────────────────────
refs = {
    1:  sql("SELECT SUM(ca_provisoire) ca, SUM(marge_provisoire) mg, AVG(perc_marge_provisoire) pct, COUNT(*) n FROM dossiers"),
    2:  sql("""SELECT dossier_ref, client_name, ca_provisoire/1e6 ca, marge_provisoire/1e6 mg,
                      perc_marge_provisoire pct FROM dossiers
               WHERE ca_provisoire>0 ORDER BY marge_provisoire DESC LIMIT 5"""),
    3:  sql("""SELECT dossier_ref, client_name, project_name, ca_provisoire/1e6 ca,
                      depense_provisoire/1e6 dep, marge_provisoire/1e6 mg, perc_marge_provisoire pct
               FROM dossiers WHERE dossier_ref='DC/2026/0154'"""),
    4:  sql("""SELECT dossier_ref, client_name, ca_provisoire/1e6 ca, marge_provisoire/1e6 mg, perc_marge_provisoire pct
               FROM dossiers WHERE lower(client_name) LIKE '%orange%' AND ca_provisoire>0
               ORDER BY ca_provisoire DESC LIMIT 5"""),
    5:  sql("""SELECT SUM(ca_provisoire)/1e9 ca_tot, SUM(marge_provisoire)/1e9 mg_tot,
                      SUM(montant_recu)/1e9 encaisse, SUM(reste_a_encaisser)/1e9 reste,
                      SUM(backlog)/1e9 backlog
               FROM dossiers WHERE strftime('%Y',date_creation)='2026'"""),
    6:  sql("""SELECT dossier_ref, client_name, marge_provisoire/1e6 mg, perc_marge_provisoire pct
               FROM dossiers WHERE perc_marge_provisoire < 5 AND ca_provisoire > 10000000
               ORDER BY perc_marge_provisoire ASC LIMIT 5"""),
    7:  sql("""SELECT d.client_name, SUM(d.ca_provisoire)/1e6 ca, AVG(d.perc_marge_provisoire) pct, COUNT(*) nb
               FROM dossiers d JOIN sale_orders s ON s.dossier_id=d.dossier_ref
               WHERE strftime('%Y',s.date_order)='2025' AND s.state IN('sale','done')
               GROUP BY d.client_name ORDER BY ca DESC LIMIT 5"""),
    8:  sql("""SELECT SUM(fournisseurs_payes)/1e9 payes, SUM(fournisseurs_restant)/1e9 restant,
                      COUNT(*) n FROM dossiers"""),
    9:  sql("""SELECT client_name, SUM(ca_provisoire)/1e6 ca, SUM(marge_provisoire)/1e6 mg,
                      AVG(perc_marge_provisoire) pct, COUNT(*) nb
               FROM dossiers GROUP BY client_name ORDER BY SUM(marge_provisoire) DESC LIMIT 5"""),
    10: sql("""SELECT dossier_ref, client_name, ca_provisoire/1e6 ca, marge_provisoire/1e6 mg,
                      perc_marge_provisoire pct, state FROM dossiers
               WHERE lower(client_name) LIKE '%versus%' ORDER BY date_creation DESC LIMIT 3"""),
}

questions = [
    (1,  "Quelle est notre marge globale totale sur tous les dossiers ?"),
    (2,  "Quels sont nos 5 dossiers les plus rentables en valeur absolue ?"),
    (3,  "Donne-moi tous les details financiers du dossier DC/2026/0154 (VERSUS BANK)"),
    (4,  "Quelle est la marge sur les dossiers Orange ?"),
    (5,  "Quel est le CA, la marge, ce qu'on a encaisse et ce qui reste a encaisser pour les dossiers 2026 ?"),
    (6,  "Quels sont nos dossiers les moins rentables (marge < 5%) avec un CA significatif ?"),
    (7,  "Pour les dossiers lies aux BDC 2025, quels clients ont le plus gros CA dans les dossiers ?"),
    (8,  "Combien on a paye aux fournisseurs et combien reste-t-il a payer ?"),
    (9,  "Top 5 clients par marge totale cumulee sur tous les dossiers"),
    (10, "Quels sont les dossiers de VERSUS BANK ?"),
]

tok = login()
print(f"Token OK — {len(questions)} questions sur les dossiers\n")

for (ref_n, q) in questions:
    sep(ref_n, q)
    t0 = time.time()
    rep = ask(tok, q, f"dos_{ref_n}")
    elapsed = time.time() - t0
    print(f"\n[AGENT — {elapsed:.1f}s — {len(rep)} chars]")
    print(rep or "(vide)")

    print(f"\n[REF SQLITE]")
    ref = refs[ref_n]
    if ref_n == 1:
        r = ref[0]
        print(f"  CA total prov : {(r['ca'] or 0)/1e9:.2f} Mds | Marge : {(r['mg'] or 0)/1e9:.2f} Mds | % moyen : {(r['pct'] or 0):.1f}% | {r['n']} dossiers")
    elif ref_n == 2:
        for r in ref: print(f"  {r['dossier_ref']} | {r['client_name'][:35]:<35} | CA={r['ca']:.0f}M | Mg={r['mg']:.0f}M ({r['pct']:.1f}%)")
    elif ref_n == 3:
        if ref: r=ref[0]; print(f"  {r['dossier_ref']} | {r['client_name']} | CA={r['ca']:.2f}M | Dep={r['dep']:.2f}M | Mg={r['mg']:.2f}M ({r['pct']:.1f}%)")
    elif ref_n == 4:
        for r in ref: print(f"  {r['dossier_ref']} | {r['client_name'][:35]:<35} | CA={r['ca']:.1f}M | Mg={r['mg']:.1f}M ({r['pct']:.1f}%)")
    elif ref_n == 5:
        r = ref[0]
        print(f"  CA={r['ca_tot']:.2f}Mds | Marge={r['mg_tot']:.2f}Mds | Encaisse={r['encaisse']:.2f}Mds | Reste={r['reste']:.2f}Mds | Backlog={r['backlog']:.2f}Mds")
    elif ref_n == 6:
        for r in ref: print(f"  {r['dossier_ref']} | {r['client_name'][:35]:<35} | Mg={r['mg']:.1f}M ({r['pct']:.1f}%)")
    elif ref_n == 7:
        for r in ref: print(f"  {r['client_name'][:35]:<35} | CA={r['ca']:.0f}M | Marge%={r['pct']:.1f}% | {r['nb']} dossiers")
    elif ref_n == 8:
        r=ref[0]; print(f"  Fournis. payes={r['payes']:.2f}Mds | Restant={r['restant']:.2f}Mds | {r['n']} dossiers")
    elif ref_n == 9:
        for r in ref: print(f"  {r['client_name'][:40]:<40} | CA={r['ca']:.0f}M | Mg={r['mg']:.0f}M ({r['pct']:.1f}%) | {r['nb']} doss.")
    elif ref_n == 10:
        for r in ref: print(f"  {r['dossier_ref']} | CA={r['ca']:.1f}M | Mg={r['mg']:.1f}M ({r['pct']:.1f}%) | {r['state']}")

print("\n\nFIN DU TEST DOSSIERS")
