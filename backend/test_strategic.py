"""
Audit stratégique : 4 rôles × 3 questions = 12 questions de direction.
Compare les réponses de l'agent IA avec les données réelles Odoo.
"""
import asyncio, httpx, json, sys, io, re
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
with open("tmp_token.txt", encoding="ascii") as f:
    TOKEN = f.read().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


# ─── Agent SSE ────────────────────────────────────────────────────────────────
async def ask_agent(question: str, session_id: str) -> str:
    full = ""
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", f"{BASE}/v1/chat/query",
            data={"text": question, "session_id": session_id, "history": "[]"},
            headers=HEADERS,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                p = line[5:].strip()
                if not p or p == "[DONE]":
                    continue
                try:
                    e = json.loads(p)
                    if e.get("type") == "token":
                        full += e.get("content", "")
                except Exception:
                    pass
    return full.strip()


# ─── Données Odoo de référence ────────────────────────────────────────────────
async def get_odoo_reference():
    """Récupère les KPIs de référence depuis Odoo directement."""
    import sys; sys.path.insert(0, ".")
    from adapters.crm.odoo_adapter import OdooAdapter
    odoo = OdooAdapter()
    ref = {}
    try:
        # CA T2 2026 (avril + mai, en cours)
        orders_t2 = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2026-04-01"],
              ["date_order", "<=", "2026-05-31"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["name", "amount_total", "currency_id", "user_id", "partner_id"], "limit": 500})
        ref["t2_nb_bdc"] = len(orders_t2)
        # Nb commerciaux distincts T2
        salespersons_t2 = {}
        for o in orders_t2:
            sp = (o.get("user_id") or [None, "Inconnu"])[1]
            salespersons_t2[sp] = salespersons_t2.get(sp, 0) + o["amount_total"]
        ref["t2_par_commercial_raw"] = sorted(salespersons_t2.items(), key=lambda x: x[1], reverse=True)[:5]

        # Factures impayées > 90 jours
        invoices_unpaid = await odoo._call("account.move", "search_read",
            [[["move_type", "=", "out_invoice"],
              ["payment_state", "in", ["not_paid", "partial"]],
              ["invoice_date_due", "<", "2026-02-20"]]],  # > 90 jours au 21/05/2026
            {"fields": ["name", "amount_residual", "invoice_date_due", "partner_id"], "limit": 200})
        ref["impayees_90j_nb"] = len(invoices_unpaid)
        ref["impayees_90j_montant"] = sum(i.get("amount_residual", 0) for i in invoices_unpaid)

        # DSO : délai moyen paiement toutes factures payées 2026
        invoices_paid = await odoo._call("account.move", "search_read",
            [[["move_type", "=", "out_invoice"],
              ["payment_state", "=", "paid"],
              ["invoice_date", ">=", "2026-01-01"]]],
            {"fields": ["invoice_date", "invoice_date_due", "amount_total"], "limit": 500})
        ref["factures_payees_2026"] = len(invoices_paid)

        # Top 5 clients T2 2026
        clients_t2 = {}
        for o in orders_t2:
            cname = (o.get("partner_id") or [None, "—"])[1]
            clients_t2[cname] = clients_t2.get(cname, 0) + o["amount_total"]
        ref["top5_clients_t2"] = sorted(clients_t2.items(), key=lambda x: x[1], reverse=True)[:5]

        # Pipeline crm.lead
        try:
            leads = await odoo._call("crm.lead", "search_read",
                [[["active", "=", True], ["type", "=", "opportunity"]]],
                {"fields": ["name", "expected_revenue", "probability", "stage_id", "user_id"], "limit": 200})
            ref["pipeline_nb_opps"] = len(leads)
            ref["pipeline_total_pondere"] = sum(
                l.get("expected_revenue", 0) * l.get("probability", 0) / 100
                for l in leads
            )
            ref["pipeline_total_brut"] = sum(l.get("expected_revenue", 0) for l in leads)
        except Exception as e:
            ref["pipeline_error"] = str(e)

        # CA S1 2026 (jan→mai, juin pas terminé)
        orders_s1 = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2026-01-01"],
              ["date_order", "<=", "2026-05-31"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["name", "amount_total", "currency_id"], "limit": 500})
        ref["s1_2026_nb"] = len(orders_s1)

        # Clients actifs 2025
        orders_2025 = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2025-01-01"],
              ["date_order", "<=", "2025-12-31"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["partner_id"], "limit": 5000})
        clients_2025 = set((o.get("partner_id") or [None])[0] for o in orders_2025 if o.get("partner_id"))
        ref["clients_actifs_2025"] = len(clients_2025)

        # Clients actifs 2024
        orders_2024 = await odoo._call("sale.order", "search_read",
            [[["date_order", ">=", "2024-01-01"],
              ["date_order", "<=", "2024-12-31"],
              ["state", "in", ["sale", "done"]]]],
            {"fields": ["partner_id"], "limit": 5000})
        clients_2024 = set((o.get("partner_id") or [None])[0] for o in orders_2024 if o.get("partner_id"))
        ref["clients_actifs_2024"] = len(clients_2024)
        retained = clients_2024 & clients_2025
        ref["taux_retention_2025"] = round(len(retained) / len(clients_2024) * 100, 1) if clients_2024 else 0
        ref["clients_perdus_2025"] = len(clients_2024 - clients_2025)
        ref["nouveaux_clients_2025"] = len(clients_2025 - clients_2024)

    except Exception as e:
        ref["odoo_error"] = str(e)
    finally:
        await odoo.close()
    return ref


# ─── Questions stratégiques ────────────────────────────────────────────────────
QUESTIONS = [
    # ── Directeur Commercial ────────────────────────────────────────────────
    {
        "role": "DIRECTEUR COMMERCIAL",
        "emoji": "💼",
        "q": "Quels sont nos 5 meilleurs clients ce trimestre (T2 2026 : avril-mai) par chiffre d'affaires, et combien ont-ils commandé ?",
        "check_key": "top5_clients_t2",
        "session": "dc-q1",
    },
    {
        "role": "DIRECTEUR COMMERCIAL",
        "emoji": "💼",
        "q": "Quel est le classement de nos commerciaux par CA généré sur ce trimestre T2 2026 (avril-mai) ? Qui performe le mieux ?",
        "check_key": "t2_par_commercial_raw",
        "session": "dc-q2",
    },
    {
        "role": "DIRECTEUR COMMERCIAL",
        "emoji": "💼",
        "q": "Quels clients importants (ayant commandé en 2024 ou 2025) n'ont pas passé de commande depuis plus de 6 mois ? Donne-moi les 10 premiers avec leur dernier achat.",
        "check_key": None,
        "session": "dc-q3",
    },
    # ── Directeur des Opérations ────────────────────────────────────────────
    {
        "role": "DIRECTEUR DES OPÉRATIONS",
        "emoji": "⚙️",
        "q": "Quel est notre exposition totale aux impayés en ce moment ? Donne-moi le montant total des factures non payées, celles dépassant 90 jours, et les 5 plus gros débiteurs.",
        "check_key": "impayees_90j_montant",
        "session": "ops-q1",
    },
    {
        "role": "DIRECTEUR DES OPÉRATIONS",
        "emoji": "⚙️",
        "q": "Quels sont les 10 clients avec le score de risque financier le plus élevé aujourd'hui ? Justifie chaque score.",
        "check_key": None,
        "session": "ops-q2",
    },
    {
        "role": "DIRECTEUR DES OPÉRATIONS",
        "emoji": "⚙️",
        "q": "Quels contrats arrivent à expiration dans les 60 prochains jours ? Quelle est leur valeur totale ?",
        "check_key": None,
        "session": "ops-q3",
    },
    # ── CODIR ────────────────────────────────────────────────────────────────
    {
        "role": "CODIR",
        "emoji": "🏢",
        "q": "Quelle est notre trajectoire de CA sur les 5 premiers mois de 2026 mois par mois ? Projette le CA probable pour fin T2 (juin 2026).",
        "check_key": "s1_2026_nb",
        "session": "codir-q1",
    },
    {
        "role": "CODIR",
        "emoji": "🏢",
        "q": "Quel est notre taux de rétention client entre 2024 et 2025 ? Combien de clients avons-nous perdus et combien de nouveaux avons-nous gagnés ?",
        "check_key": "taux_retention_2025",
        "session": "codir-q2",
    },
    {
        "role": "CODIR",
        "emoji": "🏢",
        "q": "Quel est le CA par secteur d'activité client en 2025 ? Quels secteurs sont en croissance, lesquels stagnent ?",
        "check_key": None,
        "session": "codir-q3",
    },
    # ── Directeur Général ────────────────────────────────────────────────────
    {
        "role": "DIRECTEUR GÉNÉRAL",
        "emoji": "🎯",
        "q": "Donne-moi un bilan exécutif de la performance commerciale de Neurones Technologies depuis le début 2026 : CA, clients actifs, BDC, tendance, alertes critiques.",
        "check_key": None,
        "session": "dg-q1",
    },
    {
        "role": "DIRECTEUR GÉNÉRAL",
        "emoji": "🎯",
        "q": "Quels sont nos 3 facteurs de risque financiers les plus critiques en ce moment et quelle est l'exposition totale en XOF ?",
        "check_key": None,
        "session": "dg-q2",
    },
    {
        "role": "DIRECTEUR GÉNÉRAL",
        "emoji": "🎯",
        "q": "Si tu étais directeur général de Neurones Technologies pour les 30 prochains jours, quelles seraient tes 3 priorités absolues ? Justifie avec des chiffres précis.",
        "check_key": None,
        "session": "dg-q3",
    },
]


def fmt_xof(v):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):,.0f} XOF"
    except Exception:
        return str(v)


async def main():
    print("\n" + "=" * 90)
    print("AUDIT STRATÉGIQUE IA — 4 RÔLES × 3 QUESTIONS")
    print(f"Date : {datetime.now().strftime('%d/%m/%Y %H:%M')} | Neurones Technologies")
    print("=" * 90)

    print("\n⏳ Récupération des données Odoo de référence...")
    odoo_ref = await get_odoo_reference()
    if "odoo_error" in odoo_ref:
        print(f"⚠️  Erreur Odoo partielle : {odoo_ref['odoo_error']}")
    else:
        print("✅ Données Odoo récupérées")

    current_role = None
    results = []

    for i, item in enumerate(QUESTIONS):
        if item["role"] != current_role:
            current_role = item["role"]
            print(f"\n\n{'─'*90}")
            print(f"  {item['emoji']}  {current_role}")
            print(f"{'─'*90}")

        qnum = (i % 3) + 1
        print(f"\n[Q{qnum}] {item['q']}")
        print("  🤖 Interrogation de l'agent...", end="", flush=True)

        answer = await ask_agent(item["q"], item["session"])
        # Nettoyer les balises markdown pour l'affichage
        answer_clean = answer.replace("\n", " ").replace("  ", " ")
        print(" ✓")

        # Afficher la réponse (tronquée)
        print(f"\n  📋 RÉPONSE AGENT :")
        # Afficher par lignes courtes
        words = answer.split("\n")
        for line in words[:20]:
            if line.strip():
                print(f"     {line[:130]}")
        if len(words) > 20:
            print(f"     [...{len(words)-20} lignes supplémentaires]")

        # Vérification Odoo si clé disponible
        check = item.get("check_key")
        if check and check in odoo_ref:
            odoo_val = odoo_ref[check]
            print(f"\n  🔍 VÉRIFICATION ODOO ({check}) :")
            if isinstance(odoo_val, list):
                for j, entry in enumerate(odoo_val[:5], 1):
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        print(f"     {j}. {entry[0][:40]:<40} {fmt_xof(entry[1])}")
                    else:
                        print(f"     {j}. {str(entry)[:80]}")
            elif isinstance(odoo_val, (int, float)):
                print(f"     Valeur réelle : {fmt_xof(odoo_val)}")
            else:
                print(f"     Valeur réelle : {odoo_val}")

        results.append({"role": item["role"], "q": item["q"][:60], "answer_len": len(answer)})
        await asyncio.sleep(3)

    # ─── Synthèse des données Odoo ─────────────────────────────────────────
    print("\n\n" + "=" * 90)
    print("DONNÉES ODOO RÉELLES — RÉFÉRENTIEL DE VÉRIFICATION")
    print("=" * 90)

    print(f"\n📊 T2 2026 (Avril + Mai) :")
    print(f"   Nb BDC confirmés : {odoo_ref.get('t2_nb_bdc', 'N/A')}")
    print(f"\n   Top 5 clients T2 :")
    for j, (name, ca) in enumerate(odoo_ref.get("top5_clients_t2", []), 1):
        print(f"     {j}. {name[:45]:<45} {fmt_xof(ca)}")
    print(f"\n   Top 5 commerciaux T2 (CA brut, devises mixtes) :")
    for j, (name, ca) in enumerate(odoo_ref.get("t2_par_commercial_raw", []), 1):
        print(f"     {j}. {name[:35]:<35} {fmt_xof(ca)}")

    print(f"\n💸 Impayés > 90 jours :")
    print(f"   Nb factures : {odoo_ref.get('impayees_90j_nb', 'N/A')}")
    print(f"   Montant total : {fmt_xof(odoo_ref.get('impayees_90j_montant'))}")

    print(f"\n📈 Rétention clients :")
    print(f"   Clients actifs 2024 : {odoo_ref.get('clients_actifs_2024', 'N/A')}")
    print(f"   Clients actifs 2025 : {odoo_ref.get('clients_actifs_2025', 'N/A')}")
    print(f"   Taux de rétention 2024→2025 : {odoo_ref.get('taux_retention_2025', 'N/A')}%")
    print(f"   Clients perdus : {odoo_ref.get('clients_perdus_2025', 'N/A')}")
    print(f"   Nouveaux clients : {odoo_ref.get('nouveaux_clients_2025', 'N/A')}")

    print(f"\n🔮 Pipeline commercial :")
    if "pipeline_error" in odoo_ref:
        print(f"   ⚠️  {odoo_ref['pipeline_error']}")
    else:
        print(f"   Nb opportunités actives : {odoo_ref.get('pipeline_nb_opps', 'N/A')}")
        print(f"   Pipeline brut : {fmt_xof(odoo_ref.get('pipeline_total_brut'))}")
        print(f"   Pipeline pondéré : {fmt_xof(odoo_ref.get('pipeline_total_pondere'))}")

    print(f"\n📅 S1 2026 (Jan→Mai) : {odoo_ref.get('s1_2026_nb', 'N/A')} BDC confirmés")
    print("\n" + "=" * 90)


asyncio.run(main())
