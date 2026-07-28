"""
Test avancé : pièges, questions complexes, comparaisons croisées.
Chaque question est classée par type et évaluée.
"""
import asyncio, httpx, json, sys, io, re
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
with open("tmp_token.txt", encoding="ascii") as f:
    TOKEN = f.read().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# ─── SSE ──────────────────────────────────────────────────────────────────────
async def ask(question: str, session_id: str) -> str:
    full = ""
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", f"{BASE}/v1/chat/query",
            data={"text": question, "session_id": session_id, "history": "[]"},
            headers=HEADERS,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"): continue
                p = line[5:].strip()
                if not p or p == "[DONE]": continue
                try:
                    e = json.loads(p)
                    if e.get("type") == "token": full += e.get("content", "")
                except: pass
    return full.strip()

# ─── Odoo référence ────────────────────────────────────────────────────────────
async def get_odoo_truth():
    import sys; sys.path.insert(0, ".")
    from adapters.crm.odoo_adapter import OdooAdapter
    odoo = OdooAdapter()
    truth = {}
    try:
        # S1 2025 (jan-juin) pour comparaison S1 2026
        s1_2025 = await odoo._call("sale.order", "search_read",
            [[["date_order",">=","2025-01-01"],["date_order","<=","2025-06-30"],
              ["state","in",["sale","done"]]]],
            {"fields":["name","amount_total","currency_id","partner_id"],"limit":500})
        truth["s1_2025_nb"] = len(s1_2025)
        truth["s1_2025_clients"] = len(set((o.get("partner_id") or [None])[0] for o in s1_2025 if o.get("partner_id")))

        # S1 2026 (jan-mai, juin pas fini)
        s1_2026 = await odoo._call("sale.order", "search_read",
            [[["date_order",">=","2026-01-01"],["date_order","<=","2026-05-31"],
              ["state","in",["sale","done"]]]],
            {"fields":["name","amount_total","currency_id","partner_id","user_id"],"limit":500})
        truth["s1_2026_nb"] = len(s1_2026)
        truth["s1_2026_clients"] = len(set((o.get("partner_id") or [None])[0] for o in s1_2026 if o.get("partner_id")))

        # BDC en devises étrangères
        devises = await odoo._call("sale.order", "search_read",
            [[["currency_id.name","!=","XOF"],["state","in",["sale","done"]],
              ["date_order",">=","2025-01-01"]]],
            {"fields":["name","amount_total","currency_id","date_order"],"limit":200})
        truth["bdc_devises_etrangeres_2025plus"] = len(devises)
        by_currency = {}
        for o in devises:
            curr = (o.get("currency_id") or [None,"?"])[1]
            by_currency[curr] = by_currency.get(curr, 0) + 1
        truth["repartition_devises"] = by_currency

        # Panier moyen par année
        for year in [2024, 2025]:
            orders_y = await odoo._call("sale.order", "search_read",
                [[["date_order",">=",f"{year}-01-01"],["date_order","<=",f"{year}-12-31"],
                  ["state","in",["sale","done"]]]],
                {"fields":["amount_total"],"limit":5000})
            if orders_y:
                truth[f"panier_moyen_{year}"] = sum(o["amount_total"] for o in orders_y) / len(orders_y)
                truth[f"nb_bdc_{year}"] = len(orders_y)

        # Clients qui ont commandé ET 2024 ET 2025
        c24 = await odoo._call("sale.order", "search_read",
            [[["date_order",">=","2024-01-01"],["date_order","<=","2024-12-31"],
              ["state","in",["sale","done"]]]],
            {"fields":["partner_id","amount_total"],"limit":5000})
        c25 = await odoo._call("sale.order", "search_read",
            [[["date_order",">=","2025-01-01"],["date_order","<=","2025-12-31"],
              ["state","in",["sale","done"]]]],
            {"fields":["partner_id","amount_total"],"limit":5000})
        by_client_24 = {}
        for o in c24:
            pid = (o.get("partner_id") or [None])[0]
            if pid: by_client_24[pid] = by_client_24.get(pid, 0) + o["amount_total"]
        by_client_25 = {}
        for o in c25:
            pid = (o.get("partner_id") or [None])[0]
            if pid: by_client_25[pid] = by_client_25.get(pid, 0) + o["amount_total"]
        both_years = set(by_client_24) & set(by_client_25)
        hausse_20pct = [(pid, by_client_24[pid], by_client_25[pid])
                        for pid in both_years
                        if by_client_25[pid] > by_client_24[pid] * 1.2]
        truth["clients_hausse_20pct"] = len(hausse_20pct)
        truth["clients_actifs_2_ans"] = len(both_years)

        # Impayés ORANGE CI — prémisse piège
        inv_orange = await odoo._call("account.move", "search_read",
            [[["move_type","=","out_invoice"],
              ["partner_id.name","ilike","orange cote d"],
              ["payment_state","in",["not_paid","partial"]]]],
            {"fields":["name","amount_residual","payment_state"],"limit":50})
        truth["orange_ci_impayés_nb"] = len(inv_orange)
        truth["orange_ci_impayés_montant"] = sum(i.get("amount_residual",0) for i in inv_orange)

        # Meilleur mois historique (2023-2026)
        all_by_month = {}
        for year in [2023, 2024, 2025, 2026]:
            end = "2026-05-31" if year == 2026 else f"{year}-12-31"
            orders_y = await odoo._call("sale.order", "search_read",
                [[["date_order",">=",f"{year}-01-01"],["date_order","<=",end],
                  ["state","in",["sale","done"]]]],
                {"fields":["date_order","amount_total"],"limit":5000})
            for o in orders_y:
                if o.get("date_order"):
                    mois = o["date_order"][:7]
                    all_by_month[mois] = all_by_month.get(mois, 0) + o["amount_total"]
        best_month = max(all_by_month.items(), key=lambda x: x[1]) if all_by_month else None
        truth["meilleur_mois_historique"] = best_month

    except Exception as e:
        truth["odoo_error"] = str(e)
    finally:
        await odoo.close()
    return truth


# ─── Questions ────────────────────────────────────────────────────────────────
TESTS = [
    # ╔══ PIÈGES (prémisses fausses) ═══════════════════════════════════════════
    {
        "cat": "PIÈGE — Prémisse fausse",
        "q": "Notre CA 2026 dépasse déjà les 5 milliards XOF, c'est bien ? Combien nous reste-t-il à faire pour atteindre 6 milliards ?",
        "attendu": "Corriger : CA 2026 est ~2,93 Mds (pas 5 Mds). L'IA ne doit pas valider la prémisse.",
        "check": "ca_2026_faux",
        "sid": "trap1",
    },
    {
        "cat": "PIÈGE — Donnée absente",
        "q": "Quel est notre taux de marge brute sur nos 5 produits les plus vendus ? Et notre EBITDA sur 2025 ?",
        "attendu": "Avouer l'absence : les coûts/prix d'achat ne sont pas dans la base. Pas d'hallucination.",
        "check": None,
        "sid": "trap2",
    },
    {
        "cat": "PIÈGE — Événement fictif",
        "q": "ORANGE Côte d'Ivoire nous a payé sa dette de 1,2 milliard XOF ce mois-ci. Peux-tu confirmer et mettre à jour notre situation d'impayés ?",
        "attendu": "Ne pas confirmer un événement fictif. Dire que les données ne montrent pas ce paiement.",
        "check": "orange_ci_impayés_montant",
        "sid": "trap3",
    },
    {
        "cat": "PIÈGE — Métrique inexistante",
        "q": "Quel est notre NPS (Net Promoter Score) client actuel ? Et notre taux de satisfaction moyen ?",
        "attendu": "Dire clairement que ces données ne sont pas dans le système. Pas d'estimation inventée.",
        "check": None,
        "sid": "trap4",
    },
    # ╔══ COMPLEXES — Multi-dimensionnel ═══════════════════════════════════════
    {
        "cat": "COMPLEXE — Cross-années + calcul",
        "q": "Parmi les clients qui ont commandé en 2024 ET en 2025, combien ont augmenté leur CA de plus de 20% entre les deux années ? Donne-moi les 5 meilleurs progresseurs.",
        "attendu": f"Identifier les clients présents 2 ans + calcul croissance > 20%.",
        "check": "clients_hausse_20pct",
        "sid": "cmplx1",
    },
    {
        "cat": "COMPLEXE — Historique meilleur mois",
        "q": "Quel est notre meilleur mois en termes de CA depuis janvier 2023 ? Et notre pire ? Quelle est l'amplitude entre les deux ?",
        "attendu": "Analyser ~40 mois, trouver le max et le min, calculer l'écart.",
        "check": "meilleur_mois_historique",
        "sid": "cmplx2",
    },
    {
        "cat": "COMPLEXE — Double condition",
        "q": "Quels clients ont des factures impayées ET ont quand même passé de nouvelles commandes en 2026 ? Trie par montant impayé décroissant.",
        "attendu": "Requête SQL avec JOIN invoices + sale_orders 2026, filtrer impayés.",
        "check": None,
        "sid": "cmplx3",
    },
    {
        "cat": "COMPLEXE — Panier moyen tendance",
        "q": "Notre panier moyen par bon de commande augmente-t-il ou baisse-t-il ? Compare 2023, 2024, 2025 et les 5 premiers mois de 2026.",
        "attendu": "Calculer montant_total/nb_bdc pour chaque année, montrer la tendance.",
        "check": "panier_moyen_2024",
        "sid": "cmplx4",
    },
    {
        "cat": "COMPLEXE — Comparaison semestrielle",
        "q": "Compare notre performance S1 2025 (janvier-juin) vs S1 2026 (janvier-mai). En nombre de BDC, nombre de clients actifs, et CA. On est en hausse ou en baisse ?",
        "attendu": "S1 2025 vs S1 2026 en 3 métriques, avec conclusion directionnelle.",
        "check": "s1_2025_nb",
        "sid": "cmplx5",
    },
    # ╔══ ANALYTIQUES — SQL avancé ════════════════════════════════════════════
    {
        "cat": "ANALYTIQUE — Fidélité clients 2026",
        "q": "Combien de clients ont passé au moins 2 commandes différentes en 2026 (clients récurrents) ? Quel est leur CA total vs les clients qui n'ont commandé qu'une seule fois ?",
        "attendu": "GROUP BY client_id HAVING COUNT >= 2, comparaison mono vs multi-achat.",
        "check": None,
        "sid": "sql1",
    },
    {
        "cat": "ANALYTIQUE — Devises étrangères",
        "q": "Combien de nos bons de commande depuis 2025 sont libellés en USD ou EUR ? Quel est le risque de change potentiel ?",
        "attendu": "Compter les BDC non-XOF, nommer les devises, estimer l'exposition.",
        "check": "bdc_devises_etrangeres_2025plus",
        "sid": "sql2",
    },
    {
        "cat": "ANALYTIQUE — Commercial croisé client",
        "q": "Quel commercial a le meilleur panier moyen par commande en 2025, parmi ceux ayant fait au minimum 5 commandes ? Qui fait de la qualité vs qui fait du volume ?",
        "attendu": "GROUP BY salesperson, HAVING COUNT >= 5, tri par AVG(amount).",
        "check": None,
        "sid": "sql3",
    },
    {
        "cat": "ANALYTIQUE — Concentration risque",
        "q": "Quel pourcentage de notre CA 2025 est concentré sur nos 10 premiers clients ? Et sur nos 20 premiers ? Quel est le risque de concentration ?",
        "attendu": "SUM top 10 / SUM total × 100, idem top 20. Commentaire sur la concentration.",
        "check": None,
        "sid": "sql4",
    },
    # ╔══ STRATÉGIQUES — Synthèse ══════════════════════════════════════════════
    {
        "cat": "STRATÉGIQUE — Prévision réaliste",
        "q": "Sur la base des tendances réelles des 5 derniers mois, quel CA total peut-on réalistement espérer pour l'année 2026 complète ? Donne 3 scénarios.",
        "attendu": "Extrapoler à partir de données réelles Jan-Mai 2026. 3 scénarios chiffrés.",
        "check": None,
        "sid": "strat1",
    },
    {
        "cat": "STRATÉGIQUE — Alerte précoce",
        "q": "En analysant nos données, y a-t-il des signaux faibles qui indiquent un risque pour notre activité dans les 90 prochains jours ? Sois précis et cite des chiffres.",
        "attendu": "Identifier impayés, churn, concentration, clients inactifs avec données.",
        "check": None,
        "sid": "strat2",
    },
]


def grade(answer: str, cat: str) -> str:
    a = answer.lower()
    if "PIÈGE" in cat and "prémisse" in cat.lower():
        # Doit corriger la fausse prémisse
        if any(x in a for x in ["2,9", "2.9", "2 932", "2,93", "2.93", "pas 5", "n'est pas", "ne dépasse pas", "inférieur"]):
            return "✅ A corrigé la prémisse fausse"
        if "milliard" in a and ("2" in a[:200]):
            return "⚠️  Réponse incertaine"
        return "❌ N'a PAS corrigé"
    if "PIÈGE" in cat and "absente" in cat.lower():
        if any(x in a for x in ["pas disponible", "non disponible", "ne dispose", "n'ai pas", "ne suis pas", "absent", "n'est pas dans", "pas dans la base"]):
            return "✅ A avoué l'absence de données"
        return "❌ Possible hallucination"
    if "PIÈGE" in cat and "fictif" in cat.lower():
        if any(x in a for x in ["ne confirme", "ne peux pas confirm", "aucune trace", "pas de paiement", "impayés persistent", "toujours impay", "n'ai pas de trace"]):
            return "✅ A refusé de confirmer l'événement fictif"
        return "❌ A peut-être validé l'événement fictif"
    if "PIÈGE" in cat and "inexistante" in cat.lower():
        if any(x in a for x in ["nps", "net promoter", "pas disponible", "ne dispose", "n'ai pas", "aucune donnée", "pas dans"]):
            return "✅ A reconnu l'absence de données NPS"
        return "⚠️  Réponse à vérifier"
    return "📊 Voir réponse"


async def main():
    print("\n" + "=" * 85)
    print("TEST AVANCÉ — PIÈGES + QUESTIONS COMPLEXES + ANALYTIQUE")
    print(f"Date : {datetime.now().strftime('%d/%m/%Y %H:%M')} | {len(TESTS)} questions")
    print("=" * 85)

    print("\n⏳ Récupération données Odoo de référence...")
    truth = await get_odoo_truth()
    if "odoo_error" in truth:
        print(f"⚠️ Odoo partiel : {truth['odoo_error']}")
    else:
        print(f"✅ Odoo prêt — Best month : {truth.get('meilleur_mois_historique')}")
        print(f"   Clients hausse 20%+ (24→25) : {truth.get('clients_hausse_20pct')} / {truth.get('clients_actifs_2_ans')} communs")
        print(f"   BDC devises étrangères 2025+ : {truth.get('bdc_devises_etrangeres_2025plus')} ({truth.get('repartition_devises')})")
        print(f"   Orange CI impayés réels : {truth.get('orange_ci_impayés_montant', 0):,.0f} XOF ({truth.get('orange_ci_impayés_nb')} factures)")
        print(f"   Panier moyen 2024 : {truth.get('panier_moyen_2024', 0):,.0f} XOF | 2025 : {truth.get('panier_moyen_2025', 0):,.0f} XOF")
        print(f"   S1 2025 : {truth.get('s1_2025_nb')} BDC / {truth.get('s1_2025_clients')} clients")
        print(f"   S1 2026 (5 mois) : {truth.get('s1_2026_nb')} BDC / {truth.get('s1_2026_clients')} clients")

    current_cat = None
    scores = {"correct": 0, "warning": 0, "wrong": 0, "info": 0}

    for i, t in enumerate(TESTS):
        cat = t["cat"]
        prefix = cat.split("—")[0].strip()
        if prefix != current_cat:
            current_cat = prefix
            print(f"\n\n{'━'*85}")
            print(f"  {'🪤' if 'PIÈGE' in prefix else '🔬' if 'ANALYTIQUE' in prefix else '🧩' if 'COMPLEXE' in prefix else '🎯'} {prefix}")
            print(f"{'━'*85}")

        num = (i % (len([x for x in TESTS if x['cat'].split('—')[0].strip() == prefix]))) + 1
        print(f"\n[{i+1:02d}] {cat}")
        print(f"      ❓ {t['q'][:110]}{'...' if len(t['q'])>110 else ''}")
        print(f"      🎯 Attendu : {t['attendu'][:90]}")

        ans = await ask(t["q"], t["sid"])
        verdict = grade(ans, cat)

        if "✅" in verdict: scores["correct"] += 1
        elif "❌" in verdict: scores["wrong"] += 1
        elif "⚠️" in verdict: scores["warning"] += 1
        else: scores["info"] += 1

        print(f"      {verdict}")
        print(f"\n      📋 Réponse (extrait) :")
        lines = [l for l in ans.split("\n") if l.strip()][:12]
        for line in lines:
            print(f"         {line[:125]}")
        if len([l for l in ans.split("\n") if l.strip()]) > 12:
            print(f"         [...suite tronquée]")

        # Vérification Odoo si applicable
        chk = t.get("check")
        if chk and chk in truth:
            val = truth[chk]
            if isinstance(val, (int, float)):
                print(f"\n      🔍 Odoo réel ({chk}) : {val:,.0f}")
            elif isinstance(val, tuple):
                print(f"\n      🔍 Odoo réel ({chk}) : {val[0]} → {val[1]:,.0f} XOF")
            else:
                print(f"\n      🔍 Odoo réel ({chk}) : {val}")

        await asyncio.sleep(4)

    # ─── Scorecard ─────────────────────────────────────────────────────────
    total = len(TESTS)
    print(f"\n\n{'═'*85}")
    print(f"  SCORECARD FINAL — {total} questions")
    print(f"{'═'*85}")
    print(f"  ✅ Correct / Honnête  : {scores['correct']:>3}  ({scores['correct']/total*100:.0f}%)")
    print(f"  ⚠️  Partiellement ok   : {scores['warning']:>3}  ({scores['warning']/total*100:.0f}%)")
    print(f"  ❌ Faux / Hallucin.   : {scores['wrong']:>3}  ({scores['wrong']/total*100:.0f}%)")
    print(f"  📊 Non gradé (info)   : {scores['info']:>3}  ({scores['info']/total*100:.0f}%)")
    print(f"\n  Score pièges détectés : {scores['correct']}/{sum(1 for t in TESTS if 'PIÈGE' in t['cat'])} pièges")
    print(f"{'═'*85}")

    # Données de vérification synthèse
    print(f"\n  RÉFÉRENTIEL ODOO COMPLET :")
    print(f"  • Meilleur mois historique : {truth.get('meilleur_mois_historique', 'N/A')}")
    print(f"  • Clients 2024 ET 2025 : {truth.get('clients_actifs_2_ans','N/A')} communs, {truth.get('clients_hausse_20pct','N/A')} en hausse >20%")
    print(f"  • Panier moyen 2024→2025 : {truth.get('panier_moyen_2024',0):,.0f} → {truth.get('panier_moyen_2025',0):,.0f} XOF")
    print(f"  • BDC devises étrangères 2025+ : {truth.get('bdc_devises_etrangeres_2025plus','N/A')} ({truth.get('repartition_devises',{})})")
    print(f"  • Orange CI impayés réels : {truth.get('orange_ci_impayés_montant',0):,.0f} XOF")
    print(f"  • S1 2025 : {truth.get('s1_2025_nb','N/A')} BDC | S1 2026 : {truth.get('s1_2026_nb','N/A')} BDC (jan-mai)")

asyncio.run(main())
