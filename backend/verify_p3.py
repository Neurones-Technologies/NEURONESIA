"""
Vérification P3 (small-to-big) — à lancer hors-ligne, sans serveur ni clé API.

    .\.venv\Scripts\python.exe verify_p3.py

Affiche :
  1. Stats d'index (nb chunks, mots/chunk, parents/enfants) — l'effet P3b se voit ici APRÈS un reindex?force=true
  2. Répartition parent/enfant d'un CV et d'un ABE
  3. Une recherche par type : montre si le contexte remonte le PARENT (expansion P3a)
"""
import asyncio

from adapters.vector_store.chromadb_adapter import ChromaDBAdapter
from adapters.sparse_search.bm25_adapter import BM25Adapter
from adapters.embeddings.sentence_transformers_adapter import SentenceTransformersAdapter
from core.services.rag_engine import RAGEngine


def _line():
    print("-" * 78)


async def main():
    vs = ChromaDBAdapter()
    rag = RAGEngine(vs, BM25Adapter(), SentenceTransformersAdapter(), llm=None)

    # ── 1. Stats d'index ──────────────────────────────────────────────────────
    stats = await vs.get_index_stats()
    _line()
    print("INDEX :", stats["total_chunks"], "chunks /", stats["total_documents"], "docs",
          "| mots/chunk =", stats["avg_words_per_chunk"],
          "| parents/enfants =", stats["parent_chunks"], "/", stats["child_chunks"])
    print("Par type :", {t: v["chunks"] for t, v in stats["by_doc_type"].items()})

    # ── 2. Découpage d'un CV et d'un ABE ──────────────────────────────────────
    for want in ("cv", "abe"):
        doc = next((d for d in stats["per_document"] if d["doc_type"] == want), None)
        if not doc:
            continue
        chunks = await vs.get_chunks_by_doc_id(doc["doc_id"])
        parents = [c for c in chunks if c["metadata"].get("is_parent")]
        children = [c for c in chunks if c["metadata"].get("parent_chunk_id")]
        _line()
        print(f"{want.upper()} : {doc['filename']}")
        print(f"   {len(chunks)} chunks  ->  {len(parents)} parent(s), {len(children)} enfant(s)")
        small_to_big = "OUI" if parents and children else "NON (encore en ancien format — relancer reindex?force=true)"
        print(f"   small-to-big actif : {small_to_big}")
        if chunks:
            print(f"   exemple d'id : {chunks[0]['chunk_id']}")

    # ── 3. Recherche : expansion parent (P3a) ─────────────────────────────────
    for q, dt in [("compétences ingénieur certifications", "cv"),
                  ("marché public fourniture", "abe")]:
        srcs = await rag.search(q, filter_metadata={"doc_type": dt})
        _line()
        print(f"RECHERCHE [{dt}] '{q}' -> {len(srcs)} blocs")
        for s in srcs:
            expanded = "<- PARENT" if s.parent_chunk_id else "(chunk seul)"
            clen = len(s.content or "")
            print(f"   RRF={s.relevance_score:.4f} | {s.filename[:32]:32} | "
                  f"contexte={clen:>5}c {expanded}")
    _line()


if __name__ == "__main__":
    asyncio.run(main())
