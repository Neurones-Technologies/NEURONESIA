#!/usr/bin/env python
"""Réindexe tous les CV (data/ged/cvs) en force pour appliquer la lecture vision des
certifications-logos. Backend ARRÊTÉ. Usage : .venv/Scripts/python.exe scripts/reindex_cvs_vision.py"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.settings import settings  # noqa: E402
from config.container import Container  # noqa: E402
from core.domain.document import DocumentType  # noqa: E402

SUPPORTED = {".pdf", ".docx", ".doc", ".txt"}


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    log = logging.getLogger("reindex_cvs")
    c = Container(); c._init_adapters(); c._init_services()

    cvs_dir = (Path(settings.ged_path) / "cvs").resolve()
    files = [f for f in sorted(cvs_dir.rglob("*")) if f.is_file() and f.suffix.lower() in SUPPORTED]
    log.info("Réindexation vision de %d CV depuis %s", len(files), cvs_dir)

    ok = skipped = errors = 0
    for f in files:
        try:
            if await c.ged_indexer.process(f, DocumentType.CV, force=True):
                ok += 1
            else:
                skipped += 1
                log.warning("Ignoré (quarantaine/vide) : %s", f.name)
        except Exception as exc:
            errors += 1
            log.error("Échec : %s → %s", f.name, exc)

    log.info("BILAN CV — indexés=%d ignorés=%d erreurs=%d", ok, skipped, errors)
    await c.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
