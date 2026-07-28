# -*- coding: utf-8 -*-
"""Vérifie les champs disponibles sur neurones.dossier.manager"""
import sys, io, asyncio, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, "D:/Neurones-IA/backend")
os.chdir("D:/Neurones-IA/backend")

async def main():
    from adapters.crm.odoo_adapter import OdooAdapter
    odoo = OdooAdapter()

    # 1 seul dossier pour voir tous les champs
    sample = await odoo._call("neurones.dossier.manager", "search_read",
        [[]],
        {"fields": [], "limit": 1})
    if sample:
        print("Champs disponibles :")
        for k, v in sorted(sample[0].items()):
            print(f"  {k!r:40s} = {repr(v)[:80]}")
    else:
        print("Aucun dossier trouvé")

    await odoo.close()

asyncio.run(main())
