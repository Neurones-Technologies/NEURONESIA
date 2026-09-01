"""Recalcule `sale_order_lines.vendor` avec le référentiel constructeur courant.

Deux usages, tous deux nécessaires :

- APRÈS la migration qui ajoute la colonne : l'`ALTER TABLE` pose '' sur toutes les
  lignes existantes, indistinguables des lignes réellement inclassables. Ce script
  est ce qui remplit la colonne pour le miroir déjà en place.
- APRÈS toute modification de core/services/constructeurs.py : les règles vivent
  dans le code, la colonne est une matérialisation. Ajouter une marque sans
  reclasser laisserait la base en désaccord avec le référentiel, sans aucun signal.

    python -m scripts.reclasser_constructeurs                 # dry-run (défaut)
    python -m scripts.reclasser_constructeurs --apply         # écrit
    python -m scripts.reclasser_constructeurs --top 50        # libellés à arbitrer

Le dry-run est le mode par défaut : il affiche le taux de couverture, les écarts
par rapport à la valeur en base, et les plus gros libellés NON attribués — c'est
la liste de travail pour enrichir le référentiel. `--apply` n'écrit que les lignes
dont le constructeur change réellement, ce qui rend un second passage gratuit.

Ce script ne touche QUE la colonne `vendor`. Il ne supprime rien : le nettoyage des
partenaires exclus relève de scripts/purge_partenaires_exclus.py, à jouer AVANT
pour ne pas calculer un taux de couverture sur des lignes intra-groupe.
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict

from sqlalchemy import text

from core.services.constructeurs import detect_vendor, label_of
from db.database import AsyncSessionLocal


async def reclasser(apply: bool = False, top: int = 20) -> int:
    prefixe = "" if apply else "(dry-run) "
    print(f"\n{prefixe}Reclassement des constructeurs sur sale_order_lines\n")

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(
            "SELECT line_id, product_name, product_code, vendor, "
            "       COALESCE(subtotal_xof, 0), COALESCE(display_type, '') "
            "FROM sale_order_lines"
        ))).all()

    if not rows:
        print("  Table vide — rien à reclasser.\n")
        return 0

    # Les sections et notes de devis n'ont pas de constructeur par nature : les
    # inclure dans le taux de couverture le ferait paraître mauvais sans qu'aucune
    # règle ne puisse l'améliorer. Elles restent comptées à part.
    changements: list[tuple[str, str]] = []
    par_vendor: dict[str, list] = defaultdict(lambda: [0, 0.0])
    non_attribues: list[tuple[float, str]] = []
    n_lignes = n_mise_en_forme = 0

    for line_id, nom, code, actuel, montant, display in rows:
        if display:
            n_mise_en_forme += 1
            continue
        n_lignes += 1
        detecte = detect_vendor(nom, code) or ""
        par_vendor[detecte][0] += 1
        par_vendor[detecte][1] += montant
        if not detecte:
            non_attribues.append((montant, " ".join((nom or "").split())))
        if detecte != (actuel or ""):
            changements.append((line_id, detecte))

    attribuees = n_lignes - par_vendor[""][0]
    ca_total = sum(m for _, m in par_vendor.values())
    ca_attribue = ca_total - par_vendor[""][1]

    print(f"  Lignes de produit      : {n_lignes:6}")
    print(f"  Sections/notes ignorées: {n_mise_en_forme:6}")
    print(f"  Constructeur identifié : {attribuees:6}"
          f"  ({attribuees / n_lignes * 100:5.1f} % des lignes)")
    print(f"  Couverture en montant  : {ca_attribue / 1e6:12,.0f} M XOF"
          f"  ({ca_attribue / ca_total * 100:5.1f} % de {ca_total / 1e6:,.0f} M)\n")

    print("  Constructeur                                lignes        M XOF")
    for vendor, (n, montant) in sorted(par_vendor.items(), key=lambda kv: -kv[1][1]):
        if not vendor:
            continue
        print(f"    {label_of(vendor):<40} {n:6} {montant / 1e6:12,.0f}")
    n_na, ca_na = par_vendor[""]
    print(f"    {'— NON ATTRIBUÉ':<40} {n_na:6} {ca_na / 1e6:12,.0f}\n")

    if top and non_attribues:
        non_attribues.sort(reverse=True)
        print(f"  Les {min(top, len(non_attribues))} plus gros libellés NON attribués "
              f"— liste de travail du référentiel :")
        for montant, nom in non_attribues[:top]:
            print(f"    {montant / 1e6:10,.1f} M | {nom[:110]}")
        print()

    if not changements:
        print("  Aucun changement — la base est en accord avec le référentiel.\n")
        return 0

    print(f"  {len(changements)} ligne(s) à mettre à jour.")
    if not apply:
        print("\n  Dry-run — rien n'a été écrit.")
        print("  Pour appliquer : python -m scripts.reclasser_constructeurs --apply\n")
        return len(changements)

    # Pas de sauvegarde de la base ici, contrairement à la purge : ce script ne
    # supprime rien et `vendor` est intégralement recalculable depuis le libellé.
    # Un mauvais reclassement se corrige en corrigeant les règles et en rejouant.
    async with AsyncSessionLocal() as session:
        for debut in range(0, len(changements), 500):
            lot = changements[debut:debut + 500]
            await session.execute(
                text("UPDATE sale_order_lines SET vendor = :v WHERE line_id = :i"),
                [{"v": vendor, "i": line_id} for line_id, vendor in lot],
            )
        await session.commit()
    print(f"  {len(changements)} ligne(s) mise(s) à jour.\n")
    return len(changements)


def _lire_top(argv: list[str]) -> int:
    """Valeur de --top, 20 par défaut. Un argument non numérique est une erreur."""
    if "--top" not in argv:
        return 20
    i = argv.index("--top")
    if i + 1 >= len(argv):
        print("Erreur : --top attend un nombre.")
        raise SystemExit(2)
    try:
        return int(argv[i + 1])
    except ValueError:
        print(f"Erreur : --top attend un nombre, reçu {argv[i + 1]!r}.")
        raise SystemExit(2) from None


if __name__ == "__main__":
    asyncio.run(reclasser(apply="--apply" in sys.argv, top=_lire_top(sys.argv)))
