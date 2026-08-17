"""Purge du miroir local les partenaires intra-groupe exclus.

Complément indispensable au filtre de synchronisation (`_est_exclu` dans
jobs/odoo_sync_job.py) : ce filtre empêche toute NOUVELLE écriture, mais le sync
écrit en upsert et ne supprime jamais rien — les lignes déjà présentes y
resteraient figées indéfiniment, avec un `synced_at` qui vieillit. Filtre et
purge ne se remplacent pas, ils se complètent.

N'agit QUE sur la base locale (data/local_db/neurones.db). Odoo, la source, n'est
jamais touché : la donnée y reste intacte et reste récupérable en vidant
`settings.excluded_partner_odoo_ids` puis en relançant `python run_resync.py`.

    python -m scripts.purge_partenaires_exclus            # dry-run (défaut)
    python -m scripts.purge_partenaires_exclus --apply    # supprime réellement

Le dry-run est le mode par défaut à dessein : c'est une suppression définitive.
`--apply` sauvegarde la base en `neurones.db.bak-<horodatage>` avant d'écrire.

Idempotent : un second passage ne supprime rien et ne lève pas d'erreur.

Les identifiants à exclure ne sont PAS en dur ici — ils viennent de
settings.excluded_partner_odoo_ids. Ajouter une entité = une valeur en config,
puis relancer ce script.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError

from config.settings import settings
from db.database import AsyncSessionLocal


def _requete(sql: str):
    """Compile `sql` en liant :ids / :noms comme listes (clauses IN variadiques).

    `expanding=True` est obligatoire : sans lui, SQLAlchemy refuse une liste sur
    un paramètre scalaire (ArgumentError) au lieu de l'étendre en (?, ?, …).
    On ne lie que les paramètres réellement présents dans `sql` — `bindparams`
    rejette tout nom absent du texte, et chaque clause n'en utilise qu'un seul.
    """
    lies = [bindparam(nom, expanding=True) for nom in ("ids", "noms") if f":{nom}" in sql]
    return text(sql).bindparams(*lies) if lies else text(sql)


# Chaque entrée : (table, clause WHERE, libellé). L'ordre part des tables les
# plus dépendantes vers les fiches partenaires elles-mêmes — sans contrainte FK
# déclarée en base, c'est une convention de lisibilité, pas une nécessité
# technique. Les tables aujourd'hui vides pour l'entité exclue sont traitées par
# le même code (0 ligne, sans effet) : elles resteront correctes si elle s'y
# manifeste un jour.
#
# `:ids` (liste d'IDs sous forme de chaînes, les colonnes client_id/supplier_id
# étant des VARCHAR) et `:noms` sont liés dans `_purger`.
_CIBLES: list[tuple[str, str, str]] = [
    ("invoices",           "client_id IN :ids",     "factures clients"),
    ("sale_orders",        "client_id IN :ids",     "bons de commande"),
    ("purchase_orders",    "client_id IN :ids",     "achats"),
    ("supplier_invoices",  "supplier_id IN :ids",   "factures fournisseurs"),
    ("opportunities",      "client_id IN :ids",     "opportunités"),
    ("contracts",          "client_id IN :ids",     "contrats"),
    ("projects",           "client_id IN :ids",     "projets"),
    # `dossiers` et les snapshots ne portent pas d'ID partenaire, seulement un
    # nom : c'est la seule raison d'être de settings.excluded_partner_names.
    # Comparaison sur le nom EXACT (UPPER des deux côtés), jamais en sous-chaîne
    # — dix entités « NEURONES » cohabitent en base et seule celle listée sort.
    ("dossiers",           "UPPER(TRIM(client_name)) IN :noms", "dossiers"),
    ("pipeline_snapshots", "UPPER(TRIM(client_name)) IN :noms", "snapshots pipeline"),
    ("backlog_snapshots",  "UPPER(TRIM(client_name)) IN :noms", "snapshots backlog"),
    ("clients",            "client_id IN :ids",     "fiches client"),
    ("suppliers",          "supplier_id IN :ids",   "fiches fournisseur"),
]


async def _compter(session, table: str, clause: str, params: dict) -> int:
    """Compte les lignes visées.

    Une table absente du schéma (miroir plus ancien) vaut 0 et non une erreur —
    mais seule cette erreur-là est tolérée : toute autre remonte, sinon un
    paramètre mal lié se lirait « rien à purger » et la purge passerait à côté.
    """
    try:
        result = await session.execute(
            _requete(f"SELECT COUNT(*) FROM {table} WHERE {clause}"), params
        )
        return int(result.scalar() or 0)
    except OperationalError as e:
        if "no such table" not in str(e).lower():
            raise
        print(f"  ! {table} : absente du schéma, ignorée")
        return 0


async def _references_orphelines(session, ids: set[str]) -> tuple[int, int]:
    """Compte les BDC/opportunités restants qui pointent vers des lignes supprimées.

    `sale_orders.invoice_ids` et `opportunities.order_ids` sont des tableaux JSON
    d'IDs Odoo, sans contrainte d'intégrité. Ils ne sont pas censés référencer
    l'entité exclue (ses factures appartiennent à ses propres BDC, eux aussi
    purgés), mais on le MESURE plutôt que de le supposer.
    """
    orphelins_so = orphelins_opp = 0
    for table, colonne, compteur in (
        ("sale_orders", "invoice_ids", "so"),
        ("opportunities", "order_ids", "opp"),
    ):
        try:
            rows = await session.execute(text(f"SELECT {colonne} FROM {table}"))
        except Exception:
            continue
        for (brut,) in rows:
            if not brut:
                continue
            try:
                valeurs = json.loads(brut) if isinstance(brut, str) else brut
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(valeurs, list):
                continue
            if any(str(v) in ids for v in valeurs):
                if compteur == "so":
                    orphelins_so += 1
                else:
                    orphelins_opp += 1
    return orphelins_so, orphelins_opp


async def purger(apply: bool = False) -> int:
    ids = {str(i) for i in settings.excluded_partner_odoo_ids}
    noms = {n.strip().upper() for n in settings.excluded_partner_names}

    if not ids and not noms:
        print("Aucun partenaire exclu configuré (settings.excluded_partner_odoo_ids vide).")
        return 0

    prefixe = "" if apply else "(dry-run) "
    print(f"\n{prefixe}Partenaires exclus : ids={sorted(ids)} noms={sorted(noms)}\n")

    # Listes non vides : une clause IN () est un SQL invalide. La sentinelle ""
    # ne peut correspondre à aucun client_id réel.
    params = {"ids": sorted(ids) or [""], "noms": sorted(noms) or [""]}

    async with AsyncSessionLocal() as session:
        comptes: list[tuple[str, str, str, int]] = []
        for table, clause, libelle in _CIBLES:
            n = await _compter(session, table, clause, params)
            comptes.append((table, clause, libelle, n))
            if n:
                print(f"  {libelle:24} {n:5} ligne(s)   [{table}]")

        total = sum(n for *_, n in comptes)
        if total == 0:
            print("  Rien à purger — le miroir est déjà propre.\n")
            return 0

        orph_so, orph_opp = await _references_orphelines(session, ids)
        if orph_so or orph_opp:
            print(f"\n  Références croisées : {orph_so} BDC / {orph_opp} opportunité(s) "
                  f"citent un ID exclu dans leur tableau JSON.")

        print(f"\n  TOTAL : {total} ligne(s)")

        if not apply:
            print("\n  Dry-run — rien n'a été supprimé.")
            print("  Pour appliquer : python -m scripts.purge_partenaires_exclus --apply\n")
            return total

        # Sauvegarde AVANT toute écriture : c'est le filet de sécurité du retour
        # arrière. Une purge sans sauvegarde n'est récupérable que par un resync
        # complet depuis Odoo (long, et suppose Odoo joignable).
        db = settings.local_db_path
        if db.exists():
            backup = db.with_name(f"{db.name}.bak-{datetime.now(UTC):%Y%m%d-%H%M%S}")
            shutil.copy2(db, backup)
            print(f"\n  Sauvegarde : {backup.name}")

        supprimees = 0
        for table, clause, libelle, n in comptes:
            if not n:
                continue
            result = await session.execute(
                _requete(f"DELETE FROM {table} WHERE {clause}"), params
            )
            supprimees += result.rowcount or 0
            print(f"  - {libelle:24} {result.rowcount:5} supprimée(s)")

        # Dérivés recalculables : analyses IA et briefing citent les montants
        # intra-groupe dans leur texte. Purgés ici, ils sont régénérés par les
        # crons de jobs/scheduler.py (briefing à minuit, analyses à 6h00).
        try:
            r = await session.execute(text("DELETE FROM daily_analyses"))
            if r.rowcount:
                print(f"  - {'analyses IA (régénérées)':24} {r.rowcount:5} supprimée(s)")
        except Exception as e:
            print(f"  ! daily_analyses : échec ({e})")

        await session.commit()

    briefing = settings.local_db_path.parent.parent / "briefing_store" / "latest.json"
    if briefing.exists():
        briefing.unlink()
        print(f"  - briefing figé supprimé ({briefing.name}, régénéré au prochain cron)")

    print(f"\n  {supprimees} ligne(s) supprimée(s). Le filtre de sync empêche leur retour.\n")
    return supprimees


if __name__ == "__main__":
    asyncio.run(purger(apply="--apply" in sys.argv))
