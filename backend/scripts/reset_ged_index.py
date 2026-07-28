#!/usr/bin/env python
"""
Reset de l'index GED — efface UNIQUEMENT les données documentaires (RAG) pour
permettre une ré-ingestion propre de tous les documents.

EFFACE :
  - ChromaDB (vecteurs denses)   → data/chromadb/
  - Index BM25 (sparse)          → data/bm25_index/*.pkl + *.json
  - Tables SQLite documentaires  → ged_entries, quarantine, kb_*

PRÉSERVE (jamais touché) :
  - Miroir Odoo (clients, factures, commandes, dossiers, opportunités…)
  - Comptes utilisateurs, historique de chat, budget de tokens, veille AO

⚠️  ARRÊTER LE BACKEND avant de lancer : le watcher ré-indexerait pendant le wipe
    et SQLite/ChromaDB sont ouverts par l'application.

Usage (depuis backend/) :
    python scripts/reset_ged_index.py                 # dry-run : montre ce qui serait effacé
    python scripts/reset_ged_index.py --yes           # exécute réellement
    python scripts/reset_ged_index.py --yes --vacuum  # + compacte la base SQLite
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Console Windows (cp1252) → forcer UTF-8 pour ne pas planter sur les caractères non-ASCII
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.settings import settings  # noqa: E402

# Tables documentaires à vider (enfants avant parents — FK désactivées, mais propre).
GED_TABLES = [
    "ged_entries",
    "quarantine",
    "kb_cv_experiences", "kb_cv_certifications", "kb_cv",
    "kb_ao_exigences", "kb_ao_references_demandees", "kb_ao",
    "kb_cr_actions", "kb_compte_rendu",
    "kb_pv_reserves", "kb_pv_recette",
    "kb_certification",
    "kb_attestation",
    "kb_aliases",
    "kb_projets", "kb_personnes", "kb_clients",
]

# Tables métier à NE JAMAIS toucher (affichées pour transparence).
PRESERVED_TABLES = [
    "clients", "contracts", "invoices", "projects", "sale_orders",
    "purchase_orders", "opportunities", "dossiers",
    "users", "conversations", "token_usage",
    "veille_sources", "veille_entries",
]


def _resolve(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


def reset_sqlite(db_path: Path, apply: bool, vacuum: bool) -> None:
    if not db_path.exists():
        print(f"  (base introuvable : {db_path} — rien à faire)")
        return
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        total = 0
        for table in GED_TABLES:
            if table not in existing:
                continue
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            total += n
            if n:
                print(f"  - {table:<28} {n:>7} ligne(s)" + ("" if apply else "  [dry-run]"))
            if apply and n:
                conn.execute(f"DELETE FROM {table}")
        if apply:
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if vacuum:
                conn.execute("VACUUM")
        verb = "supprimée(s)." if apply else "seraient supprimées."
        print(f"  -> {total} ligne(s) documentaire(s) {verb}")
    finally:
        conn.close()


def reset_dir(path: Path, apply: bool, label: str) -> None:
    if not path.exists():
        print(f"  ({label} absent : {path})")
        return
    print(f"  - {label} : {path}" + ("" if apply else "  [dry-run]"))
    if apply:
        shutil.rmtree(path)


def reset_bm25(path: Path, apply: bool) -> None:
    if not path.exists():
        print(f"  (index BM25 absent : {path})")
        return
    files = list(path.glob("*.pkl")) + list(path.glob("*.json"))
    if not files:
        print(f"  (aucun fichier d'index dans {path})")
        return
    for f in files:
        print(f"  - {f.name}" + ("" if apply else "  [dry-run]"))
        if apply:
            f.unlink()


def main() -> None:
    ap = argparse.ArgumentParser(description="Reset de l'index GED (RAG) pour ré-ingestion propre.")
    ap.add_argument("--yes", action="store_true", help="exécute réellement (sinon dry-run)")
    ap.add_argument("--vacuum", action="store_true", help="compacte la base SQLite après suppression")
    args = ap.parse_args()
    apply = args.yes

    db_path = _resolve(settings.local_db_path)
    chroma_path = _resolve(settings.chromadb_path)
    bm25_path = _resolve(settings.bm25_index_path)

    mode = "EXECUTION" if apply else "DRY-RUN (aucune suppression)"
    print(f"\n=== Reset index GED - {mode} ===")
    print("[!] Le backend doit etre ARRETE (watcher + acces SQLite/ChromaDB).\n")

    print("ChromaDB (vecteurs denses) :")
    reset_dir(chroma_path, apply, "collection ChromaDB")
    print("\nIndex BM25 (sparse) :")
    reset_bm25(bm25_path, apply)
    print(f"\nTables SQLite documentaires ({db_path.name}) :")
    reset_sqlite(db_path, apply, args.vacuum)

    print("\nPRÉSERVÉ (non touché) : " + ", ".join(PRESERVED_TABLES))
    if not apply:
        print("\nDry-run termine. Relancer avec --yes pour executer.")
    else:
        print("\n[OK] Reset termine. Redemarrer le backend, puis lancer la re-ingestion.")


if __name__ == "__main__":
    main()
