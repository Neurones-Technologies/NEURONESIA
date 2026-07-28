#!/usr/bin/env python
"""
Ré-ingestion complète de la GED — hors-ligne (sans serveur HTTP ni JWT).

Reconstruit l'index documentaire (ChromaDB + BM25 + registre + kb_*) à partir des
fichiers présents dans data/ged. À lancer APRÈS reset_ged_index.py, backend ARRÊTÉ.

Usage (depuis backend/) :
    .venv/Scripts/python.exe scripts/reindex_all.py
"""
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Console Windows (cp1252) → forcer UTF-8 pour les logs accentués
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.settings import settings          # noqa: E402
from config.container import Container         # noqa: E402
from core.domain.document import DocumentType  # noqa: E402

# Dossier racine → type de document (miroir de _TYPE_MAP dans api/v1/ged.py)
TYPE_MAP = {
    "cvs": DocumentType.CV,
    "offres-techniques": DocumentType.OFFRE_TECHNIQUE,
    "abe": DocumentType.ABE,
    "pv-recette": DocumentType.PV_RECETTE,
    "procedures": DocumentType.PROCEDURE,
    "fiches-techniques": DocumentType.FICHE_TECHNIQUE,
    "comptes-rendus": DocumentType.COMPTE_RENDU,
}
SUPPORTED = {".pdf", ".docx", ".doc", ".txt"}


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log = logging.getLogger("reindex_all")

    # Construire uniquement adapters + services (PAS le watcher ni le scheduler)
    container = Container()
    container._init_adapters()
    container._init_services()
    indexer = container.ged_indexer

    root = Path(settings.ged_path).resolve()
    files: list[tuple[Path, DocumentType]] = []
    if root.exists():
        for folder, doc_type in TYPE_MAP.items():
            for f in sorted((root / folder).rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    files.append((f, doc_type))

    log.info("Ré-ingestion de %d fichier(s) depuis %s", len(files), root)

    ok = skipped = errors = 0
    for f, doc_type in files:
        try:
            indexed = await indexer.process(f, doc_type, force=True)
            if indexed:
                ok += 1
            else:
                skipped += 1
                log.warning("Ignoré (quarantaine ou vide) : %s", f.name)
        except Exception as exc:
            errors += 1
            log.error("Échec : %s → %s", f.name, exc)

    # Bilan
    try:
        stats = await container.vector_store.get_index_stats()
        entries = await container.doc_registry.list_active_entries()
        log.info(
            "BILAN — indexés=%d ignorés=%d erreurs=%d | ChromaDB: %d chunks / %d docs | registre: %d docs",
            ok, skipped, errors,
            stats.get("total_chunks", 0), stats.get("total_documents", 0), len(entries),
        )
    except Exception as exc:
        log.warning("Bilan partiel (stats indisponibles) : %s", exc)
        log.info("BILAN — indexés=%d ignorés=%d erreurs=%d", ok, skipped, errors)

    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
