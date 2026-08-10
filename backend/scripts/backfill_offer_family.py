"""Backfill de `opportunities.offer_family` sur le miroir existant.

À lancer une fois après la migration ajoutant la colonne, pour ne pas attendre le
prochain sync Odoo complet. Idempotent : relançable sans effet de bord, il
réécrit la famille de chaque ligne depuis son libellé.

À relancer aussi après tout enrichissement du dictionnaire
(modules/uc_offermix/taxonomy.py) si l'on veut que les lignes déjà en base en
profitent immédiatement — sinon elles seront reclassées au sync suivant.

    python -m scripts.backfill_offer_family          # applique
    python -m scripts.backfill_offer_family --dry-run # mesure sans écrire

Affiche le taux de couverture atteint et les plus gros montants non classés :
c'est le backlog d'enrichissement de la taxonomie, et une information utile en
soi pour la Direction Commerciale (ces libellés ne disent pas ce qu'on vend).
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from db.database import AsyncSessionLocal, init_db
from db.models import OpportunityModel
from modules.uc_offermix.taxonomy import FAMILY_ORDER, classify_family, label_of


async def backfill(dry_run: bool = False) -> None:
    await init_db()  # garantit la présence de la colonne avant toute écriture

    async with AsyncSessionLocal() as session:
        opportunities = (await session.execute(select(OpportunityModel))).scalars().all()

        stats = {f: {"nb": 0, "montant": 0.0} for f in FAMILY_ORDER}
        non_classes: list[tuple[str, float]] = []
        changed = 0

        for opp in opportunities:
            family = classify_family(opp.name)
            if family:
                stats[family]["nb"] += 1
                stats[family]["montant"] += opp.expected_revenue or 0
            else:
                non_classes.append((opp.name or "(libellé vide)", opp.expected_revenue or 0))
            if opp.offer_family != family:
                changed += 1
                if not dry_run:
                    opp.offer_family = family

        if not dry_run:
            await session.commit()

    total_nb = len(opportunities)
    total_montant = sum(s["montant"] for s in stats.values()) + sum(m for _, m in non_classes)
    classe_nb = total_nb - len(non_classes)
    classe_montant = sum(s["montant"] for s in stats.values())

    def _pct(part: float, whole: float) -> float:
        return round(100 * part / whole, 1) if whole else 0.0

    print(f"{'(dry-run) ' if dry_run else ''}{total_nb} opportunités traitées, "
          f"{changed} famille(s) modifiée(s)\n")
    for family in FAMILY_ORDER:
        s = stats[family]
        print(f"  {label_of(family):14} {s['nb']:5} opp  "
              f"{round(s['montant'] / 1e6):>8} M FCFA  "
              f"({_pct(s['montant'], classe_montant)}% du classé)")
    print(f"  {'Non qualifié':14} {len(non_classes):5} opp  "
          f"{round(sum(m for _, m in non_classes) / 1e6):>8} M FCFA")
    print(f"\n  Couverture : {_pct(classe_nb, total_nb)}% en nombre, "
          f"{_pct(classe_montant, total_montant)}% en montant\n")

    if non_classes:
        print("  Plus gros montants non classés (backlog d'enrichissement) :")
        for name, montant in sorted(non_classes, key=lambda x: -x[1])[:15]:
            print(f"    {round(montant / 1e6):>6} M  {name[:70]}")


if __name__ == "__main__":
    asyncio.run(backfill(dry_run="--dry-run" in sys.argv))
