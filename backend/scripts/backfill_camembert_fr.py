#!/usr/bin/env python
"""
Backfill de la collection ChromaDB FR (chat CamemBERT) — hors-ligne, backend ARRÊTÉ.

Au lieu de re-parser/OCR/extraire au LLM tous les documents (coûteux), ce script COPIE
les chunks déjà présents dans la collection historique (`neurones_ged`) et se contente de
les RÉ-EMBARQUER avec le modèle FR (`chat_embedding_model`) dans la collection dédiée
(`chat_collection_name`). Le contenu, les ids et les métadonnées sont identiques :
seuls les vecteurs changent. Le BM25 (partagé, indexé par chunk_id) n'est PAS touché.

→ Zéro appel LLM, zéro OCR, zéro coût API. Ne modifie JAMAIS la collection historique
  (presale/veille restent intacts).

Usage (depuis backend/) :
    .venv/Scripts/python.exe scripts/backfill_camembert_fr.py
"""
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.settings import settings  # noqa: E402
from adapters.vector_store.chromadb_adapter import ChromaDBAdapter, COLLECTION_NAME  # noqa: E402
from adapters.embeddings.sentence_transformers_adapter import SentenceTransformersAdapter  # noqa: E402

_BATCH = 64


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    log = logging.getLogger("backfill_fr")

    if not settings.chat_embedding_enabled:
        log.error("chat_embedding_enabled=False — rien à faire. Active-le d'abord dans settings.")
        return

    # Source = collection historique ; cible = collection FR dédiée au chat.
    legacy = ChromaDBAdapter(collection_name=COLLECTION_NAME)
    fr = ChromaDBAdapter(collection_name=settings.chat_collection_name)
    embedder = SentenceTransformersAdapter(model_name=settings.chat_embedding_model)

    # Dump complet de la collection historique (ids + contenu + métadonnées).
    src = legacy._collection.get(include=["documents", "metadatas"])
    ids = src.get("ids") or []
    documents = src.get("documents") or []
    metadatas = src.get("metadatas") or []

    total = len(ids)
    if total == 0:
        log.error(
            "La collection historique '%s' est VIDE — rien à copier. Lance d'abord une "
            "indexation classique (scripts/reindex_all.py ou POST /ged/rebuild).",
            COLLECTION_NAME,
        )
        return

    log.info(
        "Backfill : %d chunks de '%s' → '%s' (modèle %s, %d dims attendues)",
        total, COLLECTION_NAME, settings.chat_collection_name,
        settings.chat_embedding_model, embedder.dimension,
    )

    done = 0
    for i in range(0, total, _BATCH):
        batch_ids = ids[i : i + _BATCH]
        batch_docs = documents[i : i + _BATCH]
        batch_meta = metadatas[i : i + _BATCH]
        embeddings = await embedder.embed_texts(batch_docs)
        fr._collection.upsert(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_docs,
            metadatas=batch_meta,
        )
        done += len(batch_ids)
        log.info("  … %d / %d chunks ré-embarqués", done, total)

    fr._approx_count = fr._collection.count()
    log.info(
        "TERMINÉ — collection '%s' : %d chunks (historique '%s' inchangée : %d chunks).",
        settings.chat_collection_name, fr._approx_count, COLLECTION_NAME, legacy._collection.count(),
    )


if __name__ == "__main__":
    asyncio.run(main())
