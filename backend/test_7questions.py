# -*- coding: utf-8 -*-
"""Test final des 7 questions restantes — avec délai initial de 60s"""
import sys, io, json, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"

def login():
    r = requests.post(f"{BASE}/v1/auth/login",
                      json={"email": "dtraore@neuronestech.com", "password": "1234"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

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

questions = [
    (1,  "t7q01", "Quel est notre chiffre d'affaires total en 2025 sur les bons de commande confirmés ?"),
    (2,  "t7q02", "Quels sont nos 5 meilleurs clients par CA en 2025 ?"),
    (11, "t7q11", "Combien avons-nous payé à nos fournisseurs et combien reste-t-il à payer sur les dossiers ?"),
    (12, "t7q12", "Quels sont nos 3 meilleurs commerciaux par CA en 2025 ?"),
    (13, "t7q13", "Quelle est la valeur pondérée de notre pipeline commercial actuel ?"),
    (14, "t7q14", "Pour les dossiers créés en 2025 : quel est le CA, la marge, ce qu'on a encaissé et ce qui reste ?"),
    (15, "t7q15", "Quel est l'historique complet de notre relation commerciale avec MTN CI ?"),
]

print("Attente 60s avant de démarrer (API overload recovery)...")
time.sleep(60)

tok = login()
print(f"Token OK\n")

for (num, sid, question) in questions:
    print(f"\n{'─'*70}")
    print(f"Q{num:02d}: {question}")
    t0 = time.time()
    rep, tools = ask(tok, question, sid)
    elapsed = time.time() - t0
    print(f"[{elapsed:.1f}s | outils: {', '.join(tools) or 'aucun'}]")
    ok = "overloaded" not in rep.lower() and len(rep) > 30
    print(f"{'✅ OK' if ok else '❌ OVERLOAD'}")
    if ok:
        print(rep[:600])
    time.sleep(25)

print("\nFIN")
