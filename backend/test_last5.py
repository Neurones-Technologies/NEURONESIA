# -*- coding: utf-8 -*-
import sys, io, json, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://localhost:8000"

def login():
    r = requests.post(f"{BASE}/v1/auth/login", json={"email": "dtraore@neuronestech.com", "password": "1234"}, timeout=15)
    return r.json()["access_token"]

def ask(token, question, sid):
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    data = {"text": question, "session_id": sid, "history": "[]"}
    full = ""
    tools = []
    with requests.post(f"{BASE}/v1/chat/query", data=data, headers=headers, stream=True, timeout=180) as resp:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "): continue
            d = raw[6:]
            if d == "[DONE]": break
            try:
                obj = json.loads(d)
                t = obj.get("type","")
                if t in ("text","token"): full += obj.get("text", obj.get("content",""))
                elif t == "tool_call": tools.append(obj.get("name","?"))
            except: pass
    return full.strip(), tools

questions = [
    (11, "last11", "Combien avons-nous payé à nos fournisseurs et combien reste-t-il à payer sur les dossiers ?"),
    (12, "last12", "Quels sont nos 3 meilleurs commerciaux par CA en 2025 ?"),
    (13, "last13", "Quelle est la valeur pondérée de notre pipeline commercial actuel ?"),
    (14, "last14", "Pour les dossiers créés en 2025 : quel est le CA, la marge, ce qu'on a encaissé et ce qui reste ?"),
    (15, "last15", "Quel est l'historique complet de notre relation commerciale avec MTN CI ?"),
]

print("Attente 120s (récupération rate limit)...")
time.sleep(120)
tok = login()
print("Token OK\n")

for (num, sid, q) in questions:
    print(f"Q{num:02d}: {q}")
    rep, tools = ask(tok, q, sid)
    ok = "overloaded" not in rep.lower() and len(rep) > 30
    print(f"[{'✅' if ok else '❌'}] {rep[:500] if ok else rep[:100]}")
    if not ok and num < 15:
        print("  attente 90s...")
        time.sleep(90)
    elif num < 15:
        time.sleep(30)
    print()
