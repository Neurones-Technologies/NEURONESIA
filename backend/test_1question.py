# -*- coding: utf-8 -*-
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://localhost:8000"
r = requests.post(f"{BASE}/v1/auth/login", json={"email": "dtraore@neuronestech.com", "password": "1234"}, timeout=15)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
data = {"text": "Quel est notre CA total en 2025 sur les BDC confirmés ?", "session_id": "test1q", "history": "[]"}
full = ""
with requests.post(f"{BASE}/v1/chat/query", data=data, headers=headers, stream=True, timeout=120) as resp:
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "): continue
        d = raw[6:]
        if d == "[DONE]": break
        try:
            obj = json.loads(d)
            t = obj.get("type","")
            if t in ("text","token"): full += obj.get("text", obj.get("content",""))
        except: pass
print(full or "(vide)")
