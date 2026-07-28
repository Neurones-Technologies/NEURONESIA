# -*- coding: utf-8 -*-
"""Retry pour les questions Q01, Q02, Q11, Q12, Q13, Q14, Q15"""
import sys, io, json, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"

def login():
    r = requests.post(f"{BASE}/v1/auth/login",
                      json={"email": "dtraore@neuronestech.com", "password": "1234"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

def ask(token, question, sid, max_retries=3):
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    data = {"text": question, "session_id": sid, "history": "[]"}
    for attempt in range(max_retries):
        full = ""
        tools_called = []
        try:
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
        except Exception as e:
            full = f"Erreur réseau: {e}"

        if "overloaded_error" in full or "Overloaded" in full:
            wait = 30 * (attempt + 1)
            print(f"  [Overloaded — attente {wait}s (tentative {attempt+1}/{max_retries})]")
            time.sleep(wait)
        else:
            return full.strip(), tools_called
    return full.strip(), tools_called

questions_retry = [
    (1,  "cq01r", "Quel est notre chiffre d'affaires total en 2025 sur les bons de commande confirmés ?", "CA annuel"),
    (2,  "cq02r", "Quels sont nos 5 meilleurs clients par CA en 2025 ?", "Top clients"),
    (11, "cq11r", "Combien avons-nous payé à nos fournisseurs et combien reste-t-il à payer sur les dossiers ?", "Fournisseurs"),
    (12, "cq12r", "Quels sont nos 3 meilleurs commerciaux par CA en 2025 ?", "Performance commerciaux"),
    (13, "cq13r", "Quelle est la valeur pondérée de notre pipeline commercial actuel ?", "Pipeline"),
    (14, "cq14r", "Pour les dossiers créés en 2025 : quel est le CA, la marge, ce qu'on a encaissé et ce qui reste ?", "Dossiers 2025"),
    (15, "cq15r", "Quel est l'historique complet de notre relation commerciale avec MTN CI ?", "Historique client"),
]

tok = login()
print(f"Token OK — {len(questions_retry)} questions à retenter\n")

for (num, sid, question, cat) in questions_retry:
    print(f"\n{'═'*70}")
    print(f"Q{num:02d} [{cat}]  {question}")
    print("-" * 70)
    t0 = time.time()
    rep, tools = ask(tok, question, sid)
    elapsed = time.time() - t0
    print(f"\n[IA — {elapsed:.1f}s — outils: {', '.join(tools) or 'aucun'}]")
    print(rep[:800] or "(vide)")
    time.sleep(15)

print("\nFIN DU RETRY")
