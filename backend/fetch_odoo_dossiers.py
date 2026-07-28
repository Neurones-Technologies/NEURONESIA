# -*- coding: utf-8 -*-
"""Récupère les données dossiers Odoo avec les bons noms de champs"""
import sys, io, asyncio, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, "D:/Neurones-IA/backend")
os.chdir("D:/Neurones-IA/backend")

FIELDS = [
    "name", "partner_id", "state", "date_creation",
    "amount_business_provisoire",  # CA provisoire
    "amount_ca_definitive",        # CA définitif
    "marge_provisoire",            # marge provisoire
    "marge_definitive",            # marge définitive
    "perc_marge_provisoire",       # taux marge provisoire
    "perc_marge_definitive",       # taux marge définitive
    "amount_received",             # montant reçu
    "reste_a_encaisser",           # reste à encaisser
    "amount_po_paid",              # fournisseurs payés
    "amount_po_to_cash",           # fournisseurs restant
]

async def main():
    from adapters.crm.odoo_adapter import OdooAdapter
    odoo = OdooAdapter()

    total = await odoo._call("neurones.dossier.manager", "search_count", [[]], {})
    print(f"=== Total dossiers Odoo : {total} ===\n")

    # Paginer pour tout récupérer
    all_dossiers = []
    for offset in range(0, total, 1000):
        batch = await odoo._call("neurones.dossier.manager", "search_read",
            [[]],
            {"fields": FIELDS, "limit": 1000, "offset": offset})
        all_dossiers.extend(batch)
    print(f"Dossiers chargés : {len(all_dossiers)}\n")

    # ── Q6 : Marge globale ──────────────────────────────────────────────────────
    ca = sum(d.get("amount_business_provisoire") or 0 for d in all_dossiers)
    mg = sum(d.get("marge_provisoire") or 0 for d in all_dossiers)
    pcts = [d.get("perc_marge_provisoire") or 0 for d in all_dossiers if d.get("perc_marge_provisoire")]
    enc = sum(d.get("amount_received") or 0 for d in all_dossiers)
    # reste_a_encaisser peut être False/None dans Odoo
    reste = sum((d.get("reste_a_encaisser") or 0) for d in all_dossiers)
    fp = sum(d.get("amount_po_paid") or 0 for d in all_dossiers)
    fr = sum(d.get("amount_po_to_cash") or 0 for d in all_dossiers)

    print("=== Q6 : Marge commerciale globale (ODOO RÉEL) ===")
    print(f"  CA provisoire : {ca/1e9:.3f} Mds XOF")
    print(f"  Marge provisoire : {mg/1e9:.3f} Mds XOF")
    print(f"  Taux marge moyen : {sum(pcts)/len(pcts):.1f}%  (sur {len(pcts)} dossiers avec marge)")
    print(f"  Montant encaissé : {enc/1e9:.3f} Mds XOF")
    print(f"  Reste à encaisser : {reste/1e9:.3f} Mds XOF")
    print(f"  [Fournisseurs payés : {fp/1e9:.3f} Mds]")
    print(f"  [Fournisseurs restant : {fr/1e9:.3f} Mds]")

    # ── Q11 : Fournisseurs ──────────────────────────────────────────────────────
    print("\n=== Q11 : Fournisseurs (ODOO RÉEL) ===")
    print(f"  Payés aux fournisseurs : {fp/1e9:.3f} Mds XOF")
    print(f"  Reste à payer fournisseurs : {fr/1e9:.3f} Mds XOF")

    # ── Q7 : Top 5 dossiers ─────────────────────────────────────────────────────
    print("\n=== Q7 : Top 5 dossiers (marge provisoire) ===")
    top5 = sorted(all_dossiers, key=lambda d: d.get("marge_provisoire") or 0, reverse=True)[:5]
    for d in top5:
        p = d.get("partner_id") or [None, "?"]
        pname = p[1] if len(p) > 1 else "?"
        mg_d = d.get("marge_provisoire") or 0
        pct_d = d.get("perc_marge_provisoire") or 0
        print(f"  {d['name']} | {pname} | {mg_d/1e6:.0f}M | {pct_d:.1f}%")

    # ── Q14 : Dossiers 2025 ─────────────────────────────────────────────────────
    print("\n=== Q14 : Dossiers créés en 2025 (ODOO RÉEL) ===")
    d2025 = [d for d in all_dossiers if str(d.get("date_creation") or "")[:4] == "2025"]
    ca25 = sum(d.get("amount_business_provisoire") or 0 for d in d2025)
    mg25 = sum(d.get("marge_provisoire") or 0 for d in d2025)
    enc25 = sum(d.get("amount_received") or 0 for d in d2025)
    rest25 = sum((d.get("reste_a_encaisser") or 0) for d in d2025)
    print(f"  Nb dossiers 2025 : {len(d2025)}")
    print(f"  CA 2025 : {ca25/1e9:.3f} Mds XOF")
    print(f"  Marge 2025 : {mg25/1e9:.3f} Mds XOF")
    print(f"  Encaissé 2025 : {enc25/1e9:.3f} Mds XOF")
    print(f"  Reste 2025 : {rest25/1e9:.3f} Mds XOF")

    await odoo.close()
    print("\n=== FIN ===")

asyncio.run(main())
