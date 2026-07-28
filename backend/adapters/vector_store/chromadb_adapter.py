import json
import logging
from typing import Optional

import chromadb
from chromadb.config import Settings

from core.ports.vector_store import VectorStore
from core.domain.document import Chunk, Source, DocumentType
from config.settings import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "neurones_ged"


class ChromaDBAdapter(VectorStore):
    """ChromaDB local pour le MVP — remplaçable par pgvector sans toucher les use cases."""

    def __init__(self, collection_name: str = COLLECTION_NAME):
        # collection_name : permet plusieurs collections dans le même ChromaDB — ex. une
        # collection FR dédiée au chat (neurones_ged_fr, embeddings CamemBERT) à côté de la
        # collection historique (neurones_ged) que presale continue d'interroger.
        self._collection_name = collection_name
        # anonymized_telemetry=False : coupe le posthog interne de Chroma (incompatible avec
        # cette version → spam d'ERROR 'capture() takes 1 positional argument' à chaque requête).
        self._client = chromadb.PersistentClient(
            path=str(settings.chromadb_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._get_or_create_collection()
        # Cache le count pour éviter un full-scan metadata à chaque recherche
        self._approx_count: int = self._collection.count()
        logger.info("ChromaDB initialisé — collection '%s', %d chunks indexés", self._collection_name, self._approx_count)

    def _get_or_create_collection(self):
        return self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _recreate_collection(self) -> None:
        logger.warning(
            "ChromaDB : dimension d'embedding changée — suppression de la collection '%s'. "
            "Tous les documents devront être réindexés via le bouton 'Réindexer'.",
            self._collection_name,
        )
        self._client.delete_collection(self._collection_name)
        self._collection = self._get_or_create_collection()
        self._approx_count = 0

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        metadatas = [self._build_metadata(c) for c in chunks]
        try:
            self._collection.upsert(
                ids=[c.chunk_id for c in chunks],
                embeddings=embeddings,
                documents=[c.content for c in chunks],
                metadatas=metadatas,
            )
            self._approx_count += len(chunks)
        except Exception as exc:
            if "dimension" in str(exc).lower() or "InvalidDimensionException" in type(exc).__name__:
                self._recreate_collection()
                self._collection.upsert(
                    ids=[c.chunk_id for c in chunks],
                    embeddings=embeddings,
                    documents=[c.content for c in chunks],
                    metadatas=metadatas,
                )
                self._approx_count = len(chunks)
            else:
                raise
        logger.debug("Upsert %d chunks pour doc_id=%s", len(chunks), chunks[0].doc_id)

    async def search_dense(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: Optional[dict] = None,
    ) -> list[Source]:
        where = filter_metadata if filter_metadata else None
        # Utiliser le count caché — évite un full-scan metadata (~50-200ms)
        n = max(1, min(top_k, self._approx_count or top_k))
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        sources = []
        for cid, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            sources.append(
                Source(
                    doc_id=meta["doc_id"],
                    filename=meta["filename"],
                    doc_type=DocumentType(meta.get("doc_type", "unknown")),
                    excerpt=doc[: settings.excerpt_chars],
                    relevance_score=1.0 - dist,
                    chunk_id=cid,
                    content=doc,
                    parent_chunk_id=meta.get("parent_chunk_id") or None,
                )
            )
        return sources

    async def delete_by_doc_id(self, doc_id: str) -> None:
        results = self._collection.get(where={"doc_id": doc_id})
        if results["ids"]:
            self._collection.delete(ids=results["ids"])
            self._approx_count = max(0, self._approx_count - len(results["ids"]))
            logger.info("Supprimé %d chunks pour doc_id=%s", len(results["ids"]), doc_id)

    @staticmethod
    def _build_metadata(c: Chunk) -> dict:
        """
        Construit le dict de métadonnées ChromaDB.
        Contrainte ChromaDB : les valeurs doivent être str | int | float | bool.
        Les listes et dicts extraits sont JSON-sérialisés en str.
        """
        meta = {
            "doc_id": c.doc_id,
            "filename": c.metadata.filename,
            "doc_type": c.metadata.doc_type.value,
            "client_id": c.metadata.client_id or "",
            "chunk_index": c.chunk_index,
            "is_parent": c.is_parent,
            "parent_chunk_id": c.parent_chunk_id or "",
            "contains_pii": c.metadata.contains_pii,
        }
        # Aplatir les champs extraits (scalaires directs, listes → JSON)
        for key, value in (c.metadata.extracted_fields or {}).items():
            if isinstance(value, (str, int, float, bool)):
                meta[f"ef_{key}"] = value
            elif value is not None:
                meta[f"ef_{key}"] = json.dumps(value, ensure_ascii=False)
        return meta

    async def get_doc_ids(self) -> list[str]:
        results = self._collection.get(include=["metadatas"])
        return list({m["doc_id"] for m in results["metadatas"]})

    async def inventory(self) -> dict:
        """Inventaire exhaustif de la GED : nombre réel de documents, chunks, et répartition
        par type. Contrairement à search_dense (plafonné à top_k), parcourt TOUTES les
        métadonnées → sert de source de vérité pour 'combien de documents en GED ?'.

        Chaque fichier est compté UNE fois, assigné à son doc_type majoritaire : des chunks
        périmés taggés sous un autre type (suite à une réindexation) ne le double-comptent pas,
        donc la somme de par_type égale total_documents."""
        results = self._collection.get(include=["metadatas"])
        metadatas = results.get("metadatas") or []
        # filename -> {doc_type: nb_chunks}
        type_counts: dict[str, dict[str, int]] = {}
        for m in metadatas:
            filename = m.get("filename") or m.get("doc_id") or ""
            if not filename:
                continue
            doc_type = m.get("doc_type") or "unknown"
            counts = type_counts.setdefault(filename, {})
            counts[doc_type] = counts.get(doc_type, 0) + 1
        par_type: dict[str, int] = {}
        for counts in type_counts.values():
            dominant = max(counts, key=counts.get)
            par_type[dominant] = par_type.get(dominant, 0) + 1
        return {
            "total_documents": len(type_counts),
            "total_chunks": len(metadatas),
            "par_type": dict(sorted(par_type.items())),
        }

    def reset(self) -> None:
        """Supprime puis recrée la collection vide (reconstruction à neuf)."""
        try:
            self._client.delete_collection(self._collection_name)
        except Exception as exc:
            logger.debug("reset : delete_collection sans effet (%s)", exc)
        self._collection = self._get_or_create_collection()
        self._approx_count = 0
        logger.info("ChromaDB : collection '%s' réinitialisée (rebuild)", self._collection_name)

    async def delete_orphans(self, valid_doc_ids: set[str]) -> list[str]:
        """Supprime les chunks dont le doc_id n'est plus un document actif du registre
        (orphelins laissés par d'anciennes réindexations sous un autre doc_type). Retourne
        les chunk_ids supprimés (pour purge BM25 en miroir)."""
        results = self._collection.get(include=["metadatas"])
        ids = results.get("ids") or []
        metas = results.get("metadatas") or []
        orphan_ids = [
            cid for cid, m in zip(ids, metas) if m.get("doc_id") not in valid_doc_ids
        ]
        if orphan_ids:
            self._collection.delete(ids=orphan_ids)
            self._approx_count = max(0, self._approx_count - len(orphan_ids))
            logger.info("Purge orphelins : %d chunks supprimés", len(orphan_ids))
        return orphan_ids

    # --- Lecture / observabilité ----------------------------------------------

    @staticmethod
    def _extracted_fields_from_meta(meta: dict) -> dict:
        """Reconstruit extracted_fields depuis les clés aplaties ef_* (JSON décodé si besoin)."""
        fields: dict = {}
        for key, value in meta.items():
            if not key.startswith("ef_"):
                continue
            name = key[3:]
            if isinstance(value, str) and value[:1] in ("[", "{"):
                try:
                    fields[name] = json.loads(value)
                    continue
                except (ValueError, TypeError):
                    pass
            fields[name] = value
        return fields

    async def get_chunks_by_doc_id(self, doc_id: str) -> list[dict]:
        results = self._collection.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )
        items = [
            {"chunk_id": cid, "content": doc, "metadata": meta}
            for cid, doc, meta in zip(
                results["ids"], results["documents"], results["metadatas"]
            )
        ]
        items.sort(key=lambda it: it["metadata"].get("chunk_index", 0))
        return items

    async def get_by_chunk_ids(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        results = self._collection.get(
            ids=chunk_ids,
            include=["documents", "metadatas"],
        )
        return {
            cid: {"content": doc, "metadata": meta}
            for cid, doc, meta in zip(
                results["ids"], results["documents"], results["metadatas"]
            )
        }

    async def get_index_stats(self) -> dict:
        results = self._collection.get(include=["documents", "metadatas"])
        metas = results["metadatas"] or []
        docs = results["documents"] or []

        total_chunks = len(metas)
        by_type: dict[str, dict] = {}
        per_doc: dict[str, dict] = {}
        parent_count = 0
        total_words = 0

        for meta, content in zip(metas, docs):
            doc_id = meta.get("doc_id", "?")
            doc_type = meta.get("doc_type", "unknown")
            words = len((content or "").split())
            total_words += words
            if meta.get("is_parent"):
                parent_count += 1

            d = per_doc.setdefault(doc_id, {
                "doc_id": doc_id,
                "filename": meta.get("filename", "?"),
                "doc_type": doc_type,
                "chunk_count": 0,
                "parent_count": 0,
                "total_words": 0,
            })
            d["chunk_count"] += 1
            d["total_words"] += words
            if meta.get("is_parent"):
                d["parent_count"] += 1

            t = by_type.setdefault(doc_type, {"documents": set(), "chunks": 0})
            t["chunks"] += 1
            t["documents"].add(doc_id)

        per_document = []
        for d in per_doc.values():
            cc = d["chunk_count"] or 1
            per_document.append({
                "doc_id": d["doc_id"],
                "filename": d["filename"],
                "doc_type": d["doc_type"],
                "chunk_count": d["chunk_count"],
                "parent_count": d["parent_count"],
                "avg_words": round(d["total_words"] / cc, 1),
            })
        per_document.sort(key=lambda x: x["chunk_count"])

        by_doc_type = {
            t: {"documents": len(v["documents"]), "chunks": v["chunks"]}
            for t, v in by_type.items()
        }

        total_docs = len(per_doc)
        return {
            "total_chunks": total_chunks,
            "total_documents": total_docs,
            "parent_chunks": parent_count,
            "child_chunks": total_chunks - parent_count,
            "avg_chunks_per_doc": round(total_chunks / total_docs, 1) if total_docs else 0,
            "avg_words_per_chunk": round(total_words / total_chunks, 1) if total_chunks else 0,
            "by_doc_type": by_doc_type,
            "per_document": per_document,
            "indexed_doc_ids": list(per_doc.keys()),
        }

    async def search_dense_debug(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        doc_type: Optional[str] = None,
    ) -> list[dict]:
        where = {"doc_type": doc_type} if doc_type else None
        n = max(1, min(top_k, self._approx_count or top_k))
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        out = []
        for cid, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            out.append({
                "chunk_id": cid,
                "doc_id": meta.get("doc_id", "?"),
                "filename": meta.get("filename", "?"),
                "doc_type": meta.get("doc_type", "unknown"),
                "content": doc,
                "score": round(1.0 - dist, 4),
            })
        return out
