import asyncio
import logging
from typing import Optional

from core.ports.vector_store import VectorStore
from core.ports.sparse_search import SparseSearch
from core.ports.embedder import Embedder
from core.ports.llm_gateway import LLMGateway
from core.ports.reranker import Reranker
from core.domain.document import Source, DocumentType

logger = logging.getLogger(__name__)


class RAGEngine:
    """
    Recherche hybride : Dense (ChromaDB) + Sparse (BM25) → RRF fusion → (optionnel)
    rerank cross-encoder. Fusion au niveau chunk, expansion parent (small-to-big),
    budget de contexte compté en tokens réels.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        sparse_search: SparseSearch,
        embedder: Embedder,
        llm: LLMGateway,
        top_k: int = 10,
        rerank_top_k: int = 5,
        max_per_doc: int = 2,
        token_budget=None,
        reranker: Optional[Reranker] = None,
        rerank_default: bool = False,
        rerank_candidates: int = 20,
    ):
        self._vector_store = vector_store
        self._sparse_search = sparse_search
        self._embedder = embedder
        self._llm = llm
        self._top_k = top_k
        self._rerank_top_k = rerank_top_k
        self._max_per_doc = max_per_doc
        self._token_budget = token_budget
        self._reranker = reranker
        self._rerank_default = rerank_default
        self._rerank_candidates = rerank_candidates

    def _count_tokens(self, text: str) -> int:
        """Compte en tokens réels via le TokenBudgetManager (tiktoken) si dispo,
        sinon retombe sur un comptage par mots."""
        if self._token_budget is not None:
            try:
                return self._token_budget.estimate_tokens(text)
            except Exception:
                pass
        return len(text.split())

    async def search(
        self,
        query: str,
        filter_metadata: Optional[dict] = None,
        top_k: Optional[int] = None,
        min_dense_score: Optional[float] = None,
        rerank: Optional[bool] = None,
    ) -> list[Source]:
        """
        Pipeline hybride parallèle, fusionné AU NIVEAU CHUNK :
        1. embed_query en parallèle avec sparse search (BM25, synchrone)
        2. Dense search (ChromaDB) sur le résultat de l'embedding
        3. (levier ①) plancher cosinus min_dense_score sur les candidats denses
        4. RRF fusion par chunk_id (dense + BM25), enrichissement des chunks BM25-only
        5. (optionnel) rerank cross-encoder des meilleurs candidats RRF
        6. Classement + diversité par parent (small-to-big), expansion du parent
        → retourne max rerank_top_k chunks, chacun avec son contenu complet

        `min_dense_score` (levier ①) : plancher de similarité cosinus. Les candidats denses
        sous ce seuil sont écartés AVANT la fusion — on ne garde que les documents
        sémantiquement proches au lieu de remplir le quota avec des voisins lointains.
        Le score RRF étant purement rangé (≈0.016–0.05), il ne peut pas servir de plancher :
        c'est bien le cosinus dense (1.0 − distance) qui filtre.
        rerank : None → valeur par défaut (settings) ; True/False force par appel.
        """
        effective_top_k = top_k or self._top_k

        # Lancer embed + BM25 en parallèle (BM25 est synchrone → threadpool)
        embed_task = asyncio.create_task(self._embedder.embed_query(query))
        sparse_task = asyncio.create_task(
            asyncio.to_thread(self._sparse_search.search, query, effective_top_k)
        )
        query_embedding, sparse_results = await asyncio.gather(embed_task, sparse_task)

        dense_results = await self._vector_store.search_dense(
            query_embedding=query_embedding,
            top_k=effective_top_k,
            filter_metadata=filter_metadata,
        )

        # Levier ① — plancher de pertinence : un plus proche voisin lointain (cosinus faible)
        # n'est PAS une vraie correspondance. On l'écarte AVANT la fusion, tant que le cosinus
        # est encore porté par relevance_score (le RRF l'écrasera ensuite par un score de rang).
        # Les chunks BM25-only restent éligibles (enrichis plus bas) : un match lexical exact
        # (ex. "Commvault") absent du top-k dense remonte tout de même via la voie sparse.
        if min_dense_score is not None:
            kept = [s for s in dense_results if s.relevance_score >= min_dense_score]
            if len(kept) < len(dense_results):
                logger.debug(
                    "RAG floor : %d/%d candidats denses écartés (<%.2f) pour '%s'",
                    len(dense_results) - len(kept), len(dense_results), min_dense_score, query[:40],
                )
            dense_results = kept

        # ── Fusion RRF par chunk_id (dense et BM25 partagent la même clé) ──────
        k = 60
        scores: dict[str, float] = {}
        by_chunk: dict[str, Source] = {}
        for rank, src in enumerate(dense_results):
            cid = src.chunk_id or src.doc_id
            scores[cid] = scores.get(cid, 0.0) + 1 / (k + rank + 1)
            by_chunk[cid] = src
        for rank, (cid, _score) in enumerate(sparse_results):
            scores[cid] = scores.get(cid, 0.0) + 1 / (k + rank + 1)

        # Enrichir les chunks remontés UNIQUEMENT par BM25 (absents du dense).
        # Sans filtre dense : le filtre metadata ne s'applique pas à BM25, donc on
        # respecte tout de même filter_metadata en écartant les types non voulus.
        missing = [cid for cid in scores if cid not in by_chunk]
        if missing:
            enriched = await self._vector_store.get_by_chunk_ids(missing)
            wanted_type = (filter_metadata or {}).get("doc_type")
            for cid, data in enriched.items():
                meta = data["metadata"]
                if wanted_type and meta.get("doc_type") != wanted_type:
                    continue
                content = data["content"] or ""
                by_chunk[cid] = Source(
                    doc_id=meta.get("doc_id", ""),
                    filename=meta.get("filename", "?"),
                    doc_type=DocumentType(meta.get("doc_type", "unknown")),
                    excerpt=content[:300],
                    relevance_score=0.0,
                    chunk_id=cid,
                    content=content,
                    parent_chunk_id=meta.get("parent_chunk_id") or None,
                )

        ranked_ids = sorted(
            (cid for cid in scores if cid in by_chunk),
            key=lambda c: scores[c],
            reverse=True,
        )

        # ── (optionnel) Rerank cross-encoder des meilleurs candidats RRF ──────
        rerank_on = (rerank if rerank is not None else self._rerank_default) and self._reranker is not None
        rerank_scores: dict[str, float] = {}
        if rerank_on and ranked_ids:
            cand = ranked_ids[: self._rerank_candidates]
            try:
                docs = [(by_chunk[c].content or by_chunk[c].excerpt or "") for c in cand]
                rr = await self._reranker.rerank(query, docs)
                rerank_scores = {cand[i]: rr[i] for i in range(min(len(cand), len(rr)))}
                cand_sorted = sorted(cand, key=lambda c: rerank_scores.get(c, float("-inf")), reverse=True)
                ranked_ids = cand_sorted + ranked_ids[self._rerank_candidates:]
            except Exception as e:
                logger.warning("Reranker indisponible, fallback RRF : %s", e)
                rerank_scores = {}

        # ── Classement + diversité, dédoublonné par PARENT (small-to-big) ─────
        # Plusieurs enfants d'un même parent → un seul bloc de contexte.
        per_doc: dict[str, int] = {}
        seen_ctx: set[str] = set()
        selected: list[Source] = []
        for cid in ranked_ids:
            src = by_chunk[cid]
            ctx_key = src.parent_chunk_id or cid  # le parent porte le contexte
            if ctx_key in seen_ctx:
                continue
            if per_doc.get(src.doc_id, 0) >= self._max_per_doc:
                continue
            seen_ctx.add(ctx_key)
            per_doc[src.doc_id] = per_doc.get(src.doc_id, 0) + 1
            # score affiché : rerank si appliqué, sinon RRF (pas le cosinus dense brut)
            src.relevance_score = rerank_scores.get(cid, scores[cid])
            selected.append(src)
            if len(selected) >= self._rerank_top_k:
                break

        # ── Expansion parent : remonter le contenu complet du parent ──────────
        parent_ids = [s.parent_chunk_id for s in selected if s.parent_chunk_id]
        parents = await self._vector_store.get_by_chunk_ids(parent_ids) if parent_ids else {}

        result: list[Source] = []
        for src in selected:
            parent = parents.get(src.parent_chunk_id) if src.parent_chunk_id else None
            # content = parent (contexte large) si dispo, sinon le chunk lui-même.
            # excerpt = l'enfant (passage précis) pour la citation.
            context_text = (parent["content"] if parent else src.content) or src.content
            result.append(Source(
                doc_id=src.doc_id,
                filename=src.filename,
                doc_type=src.doc_type,
                excerpt=src.excerpt,
                relevance_score=src.relevance_score,
                chunk_id=src.chunk_id,
                content=context_text,
                parent_chunk_id=src.parent_chunk_id,
            ))

        logger.debug(
            "RAG: %d blocs (%d docs, %d via parent) pour '%s'",
            len(result), len(per_doc), len(parent_ids), query[:50],
        )
        return result

    async def inventory(self) -> dict:
        """Inventaire exhaustif de la GED (total documents/chunks + répartition par type).
        Source de vérité pour les questions quantitatives ('combien de documents ?'),
        que la recherche sémantique plafonnée à rerank_top_k ne peut pas répondre."""
        return await self._vector_store.inventory()

    async def get_full_document(self, doc_id: str) -> Optional[dict]:
        """Reconstruit le TEXTE INTÉGRAL d'un document à partir de tous ses chunks
        (ordonnés par chunk_index), sans le plafond de la recherche sémantique.

        Sert à décrire l'histoire complète d'une personne (CV) plutôt que le seul
        fragment qui matche une recherche. Retourne None si le doc_id est inconnu.
        """
        chunks = await self._vector_store.get_chunks_by_doc_id(doc_id)
        if not chunks:
            return None
        meta0 = chunks[0].get("metadata") or {}
        texte = "\n".join((c.get("content") or "").strip() for c in chunks).strip()
        return {
            "doc_id": doc_id,
            "filename": meta0.get("filename") or meta0.get("doc_id") or doc_id,
            "doc_type": meta0.get("doc_type"),
            "nb_chunks": len(chunks),
            "texte_integral": texte,
        }

    async def search_diverse(
        self,
        query: str,
        doc_types: list[str],
        per_type: int = 2,
        min_dense_score: Optional[float] = None,
    ) -> list[Source]:
        """
        Recherche par type de document en parallèle (plus rapide que séquentiel).

        `min_dense_score` (levier ①) : plancher de similarité cosinus appliqué à CHAQUE type —
        sans lui, le top-2 d'un type est renvoyé même hors-sujet (un AO Odoo remontait toujours
        2 ABE Cisco/Fortinet). Le fallback ne se déclenche que si vraiment trop peu de résultats
        et reste BORNÉ aux doc_types demandés ET au plancher (plus de bourrage hors-type/hors-sujet).
        """
        tasks = [
            self.search(query=query, filter_metadata={"doc_type": dt},
                        top_k=per_type * 3, min_dense_score=min_dense_score)
            for dt in doc_types
        ]
        results_per_type = await asyncio.gather(*tasks, return_exceptions=True)

        all_sources: list[Source] = []
        seen_filenames: set[str] = set()

        for res in results_per_type:
            if isinstance(res, Exception):
                logger.debug("search_diverse partiel: %s", res)
                continue
            count = 0
            for src in res:
                if src.filename not in seen_filenames and count < per_type:
                    all_sources.append(src)
                    seen_filenames.add(src.filename)
                    count += 1

        # Fallback si trop peu de résultats — RESTREINT aux types demandés et au même plancher,
        # pour ne jamais réintroduire un document hors-domaine (ex. un CV ou une ABE réseau).
        if len(all_sources) < 3:
            try:
                general = await self.search(query=query, top_k=10, min_dense_score=min_dense_score)
                for src in general:
                    if src.filename not in seen_filenames and src.doc_type.value in doc_types:
                        all_sources.append(src)
                        seen_filenames.add(src.filename)
            except Exception:
                pass

        all_sources.sort(key=lambda s: s.relevance_score, reverse=True)
        return all_sources

    async def build_context(self, sources: list[Source], max_tokens: int = 3000) -> str:
        """Assemble le contexte LLM à partir du CONTENU COMPLET des chunks, borné
        par max_tokens comptés en TOKENS RÉELS (tiktoken via TokenBudgetManager).
        La dernière entrée est tronquée plutôt qu'écartée pour remplir le budget."""
        if not sources:
            return ""
        parts: list[str] = []
        total = 0
        for src in sources:
            # content = contenu complet du chunk (parent si small-to-big), excerpt = repli.
            # Le budget est borné en tokens réels (tiktoken) plus bas.
            body = src.content or src.excerpt
            header = f"[{src.filename} | {src.doc_type.value}]\n"
            entry = header + body
            entry_tokens = self._count_tokens(entry)
            if total + entry_tokens > max_tokens:
                remaining = max_tokens - total
                if remaining > 60:
                    # tronque le corps pour tenir dans le budget (≈ 1 mot ≤ 1 token)
                    parts.append(header + " ".join(body.split()[:remaining]))
                break
            parts.append(entry)
            total += entry_tokens
        return "\n\n---\n\n".join(parts)

    async def search_debug(
        self,
        query: str,
        top_k: int = 10,
        doc_type: Optional[str] = None,
        rrf_k: int = 60,
    ) -> dict:
        """
        Variante d'inspection (non utilisée en prod) : retourne le détail chunk par
        chunk avec les scores dense, sparse (BM25) et RRF séparés, SANS dédoublonnage
        par filename. Sert le playground de la page GED pour visualiser ce que le
        retrieval remonte réellement.
        """
        embed_task = asyncio.create_task(self._embedder.embed_query(query))
        sparse_task = asyncio.create_task(
            asyncio.to_thread(self._sparse_search.search, query, top_k)
        )
        query_embedding, sparse_results = await asyncio.gather(embed_task, sparse_task)

        dense_results = await self._vector_store.search_dense_debug(
            query_embedding=query_embedding,
            top_k=top_k,
            doc_type=doc_type,
        )

        # Agrégation par chunk_id
        chunks: dict[str, dict] = {}
        for rank, d in enumerate(dense_results):
            chunks[d["chunk_id"]] = {
                **d,
                "dense_rank": rank + 1,
                "dense_score": d["score"],
                "sparse_rank": None,
                "sparse_score": None,
                "rrf_score": 1 / (rrf_k + rank + 1),
            }

        for rank, (cid, score) in enumerate(sparse_results):
            entry = chunks.get(cid)
            if entry is None:
                entry = {
                    "chunk_id": cid, "doc_id": None, "filename": None,
                    "doc_type": None, "content": None,
                    "dense_rank": None, "dense_score": None,
                    "rrf_score": 0.0,
                }
                chunks[cid] = entry
            entry["sparse_rank"] = rank + 1
            entry["sparse_score"] = round(float(score), 4)
            entry["rrf_score"] += 1 / (rrf_k + rank + 1)

        # Enrichir les chunks trouvés uniquement par BM25 (contenu absent du dense)
        missing = [cid for cid, c in chunks.items() if c["content"] is None]
        if missing:
            enriched = await self._vector_store.get_by_chunk_ids(missing)
            for cid, data in enriched.items():
                meta = data["metadata"]
                chunks[cid].update({
                    "doc_id": meta.get("doc_id"),
                    "filename": meta.get("filename"),
                    "doc_type": meta.get("doc_type", "unknown"),
                    "content": data["content"],
                })

        ranked = sorted(chunks.values(), key=lambda c: c["rrf_score"], reverse=True)
        for c in ranked:
            c["rrf_score"] = round(c["rrf_score"], 6)
            if c.get("content"):
                c["excerpt"] = c["content"][:500]
                c["word_count"] = len(c["content"].split())
            else:
                c["excerpt"] = ""
                c["word_count"] = 0
            c.pop("content", None)
            c.pop("score", None)

        return {
            "query": query,
            "doc_type": doc_type,
            "top_k": top_k,
            "dense_hits": len(dense_results),
            "sparse_hits": len(sparse_results),
            "results": ranked[:top_k],
        }
