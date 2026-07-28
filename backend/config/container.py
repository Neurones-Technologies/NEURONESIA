"""
Dependency injection container.
Câble les ports (interfaces abstraites) aux adapters (implémentations concrètes).
Changer un adapter ici ne nécessite aucune modification dans les use cases.
"""
import logging

from config.settings import settings

logger = logging.getLogger(__name__)


class Container:
    """Registre central des dépendances — instancié une fois au démarrage."""

    def __init__(self):
        self._llm_haiku = None
        self._llm_sonnet = None
        self._embedder = None
        self._embedder_fr = None          # embedder CamemBERT dédié au chat (uc02)
        self._vector_store = None
        self._vector_store_fr = None      # collection ChromaDB FR dédiée au chat
        self._rag_engine_fr = None        # RAGEngine FR (chat) ; legacy reste pour presale
        self._sparse_search = None
        self._reranker = None
        self._pdf_parser = None
        self._docx_parser = None
        self._ged_storage = None
        self._doc_registry = None
        self._warmup_task = None  # référence forte : sinon la tâche warm-up peut être GC avant exécution
        self._crm_repo = None
        self._odoo_adapter = None
        self._cache = None
        self._token_budget = None
        self._rag_engine = None
        self._query_dispatcher = None
        self._ged_indexer = None
        self._data_shield = None
        self._scheduler = None
        self._ged_watcher = None
        self._chunking_router = None
        self._metadata_extractor = None
        self._quality_validator = None
        self._pii_detector = None
        self._quarantine = None
        self._structured_extractor = None
        self._kb_repository = None
        self._classifier = None
        self._entity_resolver = None
        self._vision = None
        self._ro_sql = None

    async def startup(self):
        logger.info("Initialisation des adapters...")
        self._init_adapters()
        self._init_services()
        await self._start_jobs()
        self._warm_up_local_embedder()
        logger.info("Container prêt.")

    def _warm_up_local_embedder(self):
        """Précharge sentence-transformers en tâche de fond pour éviter le cold-start
        (~6s) au premier scoring quand OpenAI est en quota épuisé. Non bloquant : ne
        retarde pas 'Application startup complete'."""
        if not settings.embed_fallback_enabled:
            return
        import asyncio

        async def _load():
            try:
                from adapters.embeddings.sentence_transformers_adapter import _load_model
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _load_model, settings.embed_fallback_model)
                logger.info("Warm-up : modèle d'embeddings local préchargé.")
                # Précharge aussi le modèle FR (CamemBERT) du chat s'il est activé : évite
                # le cold-start (~6s) à la 1ʳᵉ question GED.
                if settings.chat_embedding_enabled:
                    await loop.run_in_executor(None, _load_model, settings.chat_embedding_model)
                    logger.info("Warm-up : modèle d'embeddings chat FR (%s) préchargé.", settings.chat_embedding_model)
            except Exception as exc:
                logger.warning("Warm-up embeddings local échoué (non bloquant) : %s", exc)

        # Garder une référence forte : asyncio ne tient qu'une réf faible aux tâches, une
        # tâche sans réf peut être garbage-collectée avant de tourner (d'où le warm-up qui
        # ne se déclenchait qu'à la 1ʳᵉ requête au lieu du démarrage).
        self._warmup_task = asyncio.create_task(_load())

    async def shutdown(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
        if self._ged_watcher:
            self._ged_watcher.stop()
        if self._odoo_adapter:
            await self._odoo_adapter.close()
        if self._ro_sql:
            await self._ro_sql.dispose()

    def _init_adapters(self):
        from adapters.llm.claude_haiku_adapter import ClaudeHaikuAdapter
        from adapters.llm.claude_sonnet_adapter import ClaudeSonnetAdapter
        from adapters.embeddings.openai_embed_adapter import OpenAIEmbedAdapter
        from adapters.vector_store.chromadb_adapter import ChromaDBAdapter
        from adapters.sparse_search.bm25_adapter import BM25Adapter
        from adapters.parser.pdf_adapter import PDFAdapter
        from adapters.parser.docx_adapter import DocxAdapter
        from adapters.storage.local_ged_adapter import LocalGEDAdapter
        from adapters.registry.sqlite_registry_adapter import SQLiteRegistryAdapter
        from adapters.crm.local_crm_adapter import LocalCRMAdapter
        from adapters.cache.redis_adapter import RedisAdapter

        from adapters.llm.openai_gpt_adapter import OpenAIGPTAdapter
        from adapters.llm.fallback_llm_adapter import FallbackLLMAdapter

        _haiku = ClaudeHaikuAdapter()
        _sonnet = ClaudeSonnetAdapter()
        _gpt = OpenAIGPTAdapter()

        if settings.llm_fallback_enabled:
            if settings.ollama_enabled:
                from adapters.llm.ollama_adapter import OllamaAdapter
                _ollama = OllamaAdapter()
                # Chaîne 3 niveaux : Claude → GPT-4o-mini → Ollama local
                _gpt_with_local = FallbackLLMAdapter(primary=_gpt, fallback=_ollama)
                self._llm_haiku = FallbackLLMAdapter(primary=_haiku, fallback=_gpt_with_local)
                self._llm_sonnet = FallbackLLMAdapter(primary=_sonnet, fallback=_gpt_with_local)
                logger.info("LLM fallback activé : Claude → GPT-4o-mini → Ollama (%s)", settings.ollama_model)
            else:
                self._llm_haiku = FallbackLLMAdapter(primary=_haiku, fallback=_gpt)
                self._llm_sonnet = FallbackLLMAdapter(primary=_sonnet, fallback=_gpt)
                logger.info("LLM fallback activé : Claude → GPT-4o-mini")
        else:
            self._llm_haiku = _haiku
            self._llm_sonnet = _sonnet
        if settings.embedding_backend == "local":
            # Backend unique local : un seul modèle à l'indexation ET à la requête (évite Cause A)
            from adapters.embeddings.sentence_transformers_adapter import SentenceTransformersAdapter
            self._embedder = SentenceTransformersAdapter(model_name=settings.embed_fallback_model)
            logger.info("Embeddings : local sentence-transformers (%s) — backend unique", settings.embed_fallback_model)
        elif settings.embed_fallback_enabled:
            from adapters.embeddings.sentence_transformers_adapter import SentenceTransformersAdapter
            from adapters.embeddings.fallback_embed_adapter import FallbackEmbedAdapter
            _local = SentenceTransformersAdapter(model_name=settings.embed_fallback_model)
            self._embedder = FallbackEmbedAdapter(primary=OpenAIEmbedAdapter(), fallback=_local)
            logger.info("Embed fallback activé : OpenAI → sentence-transformers (%s) si quota épuisé", settings.embed_fallback_model)
        else:
            self._embedder = OpenAIEmbedAdapter()
        self._vector_store = ChromaDBAdapter()
        # ── Embeddings FR (CamemBERT) pour le chat + documents (uc02) ──────────────
        # Collection ChromaDB dédiée (chat_collection_name) embarquée avec un modèle FR natif,
        # ISOLÉE de la collection historique que presale/veille continuent d'interroger.
        # Kill-switch : chat_embedding_enabled=False → le chat retombe sur l'embedder legacy.
        if settings.chat_embedding_enabled:
            from adapters.embeddings.sentence_transformers_adapter import SentenceTransformersAdapter
            self._embedder_fr = SentenceTransformersAdapter(model_name=settings.chat_embedding_model)
            self._vector_store_fr = ChromaDBAdapter(collection_name=settings.chat_collection_name)
            logger.info(
                "Embeddings chat FR : %s → collection '%s' (isolée de presale)",
                settings.chat_embedding_model, settings.chat_collection_name,
            )
        self._sparse_search = BM25Adapter()
        self._pdf_parser = PDFAdapter()
        self._docx_parser = DocxAdapter()
        self._ged_storage = LocalGEDAdapter()
        self._doc_registry = SQLiteRegistryAdapter()
        from adapters.kb.readonly_sql_adapter import ReadOnlySqlAdapter
        self._ro_sql = ReadOnlySqlAdapter(
            db_path=settings.local_db_path,
            timeout_seconds=settings.sql_query_timeout_seconds,
        )
        from adapters.crm.odoo_adapter import OdooAdapter
        self._crm_repo = LocalCRMAdapter()
        self._odoo_adapter = OdooAdapter()
        self._cache = RedisAdapter()
        self._token_budget = self._build_token_budget()
        # Reranker cross-encoder (P6) — instance toujours créée (modèle chargé
        # paresseusement au 1er usage), pour rester testable à la demande même si
        # rerank_enabled=False (le chat ne l'active alors pas par défaut).
        try:
            from adapters.reranker.cross_encoder_adapter import CrossEncoderRerankAdapter
            self._reranker = CrossEncoderRerankAdapter(settings.rerank_model)
        except Exception as e:
            logger.warning("Reranker non initialisé : %s", e)
            self._reranker = None

    def _build_token_budget(self):
        from core.services.token_budget_manager import TokenBudgetManager
        return TokenBudgetManager(
            monthly_budget_fcfa=settings.token_budget_monthly_fcfa,
            alert_threshold_pct=settings.token_alert_threshold_pct,
        )

    def _init_services(self):
        from core.services.rag_engine import RAGEngine
        from core.services.query_dispatcher import QueryDispatcher
        from core.services.ged_indexer import GEDIndexer
        from core.services.data_shield import DataShield
        from core.services.chunking.router import ChunkingRouter
        from core.services.metadata_extractor import MetadataExtractor
        from core.services.quality_validator import QualityValidator
        from core.services.pii_detector import PIIDetector
        from core.services.structured_extractor import StructuredExtractor
        from core.services.document_classifier import DocumentClassifier
        from core.services.entity_resolver import EntityResolver
        from adapters.registry.quarantine_adapter import QuarantineAdapter
        from adapters.kb.sqlite_kb_adapter import SQLiteKBAdapter

        self._data_shield = DataShield()
        self._chunking_router = ChunkingRouter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self._metadata_extractor = MetadataExtractor(llm=self._llm_haiku)
        self._quality_validator = QualityValidator()
        self._pii_detector = PIIDetector()
        self._quarantine = QuarantineAdapter()
        self._kb_repository = SQLiteKBAdapter()
        self._structured_extractor = StructuredExtractor(
            llm=self._llm_haiku,
            confidence_threshold=settings.extraction_confidence_threshold,
            text_limit=settings.structured_extract_text_limit,
        )
        self._classifier = DocumentClassifier(llm=self._llm_haiku)
        self._entity_resolver = EntityResolver(
            auto_threshold=settings.entity_match_auto_threshold,
            review_threshold=settings.entity_match_review_threshold,
        )
        # Vision des pages-images (tous docs) — adaptateur Claude DIRECT (la méthode
        # generate_with_images vit sur l'adaptateur concret, pas sur la chaîne de fallback).
        if settings.vision_enabled:
            from core.services.document_vision_extractor import DocumentVisionExtractor
            from adapters.llm.claude_haiku_adapter import ClaudeHaikuAdapter
            self._vision = DocumentVisionExtractor(
                vision_llm=ClaudeHaikuAdapter(),
                max_pages=settings.vision_max_pages,
                area_ratio=settings.vision_area_ratio,
                dpi=settings.vision_dpi,
            )
            # Injection tardive dans le parser PDF : construit dans _init_adapters(),
            # AVANT que ce vision extractor n'existe (celui-ci a besoin de l'adaptateur
            # Claude direct) — voir PDFAdapter.set_vision_extractor. Bascule les scans
            # sur la vision (réseau, parallèle) au lieu de l'OCR Tesseract séquentiel.
            self._pdf_parser.set_vision_extractor(self._vision)
        self._rag_engine = RAGEngine(
            vector_store=self._vector_store,
            sparse_search=self._sparse_search,
            embedder=self._embedder,
            llm=self._llm_haiku,
            top_k=settings.retrieval_top_k,
            rerank_top_k=settings.rerank_top_k,
            token_budget=self._token_budget,
            reranker=self._reranker,
            rerank_default=settings.rerank_enabled,
            rerank_candidates=settings.rerank_candidates,
        )
        # RAGEngine FR (chat) : même config, mais embedder CamemBERT + collection FR.
        # Le BM25 (sparse) est partagé : il est indexé par chunk_id, indépendant du modèle.
        # Kill-switch off → le chat réutilise simplement le moteur legacy.
        if settings.chat_embedding_enabled and self._vector_store_fr is not None:
            self._rag_engine_fr = RAGEngine(
                vector_store=self._vector_store_fr,
                sparse_search=self._sparse_search,
                embedder=self._embedder_fr,
                llm=self._llm_haiku,
                top_k=settings.retrieval_top_k,
                rerank_top_k=settings.rerank_top_k,
                token_budget=self._token_budget,
                reranker=self._reranker,
                rerank_default=settings.rerank_enabled,
                rerank_candidates=settings.rerank_candidates,
            )
        else:
            self._rag_engine_fr = self._rag_engine
        self._query_dispatcher = QueryDispatcher(
            llm=self._llm_haiku,
            rag_engine=self._rag_engine_fr,
            crm_repo=self._crm_repo,
        )
        self._ged_indexer = GEDIndexer(
            vector_store=self._vector_store,
            sparse_search=self._sparse_search,
            embedder=self._embedder,
            registry=self._doc_registry,
            pdf_parser=self._pdf_parser,
            docx_parser=self._docx_parser,
            chunking_router=self._chunking_router,
            metadata_extractor=self._metadata_extractor,
            quality_validator=self._quality_validator,
            pii_detector=self._pii_detector,
            quarantine=self._quarantine,
            structured_extractor=self._structured_extractor,
            kb_repository=self._kb_repository,
            classifier=self._classifier,
            entity_resolver=self._entity_resolver,
            vision_extractor=self._vision,
            secondary_targets=(
                [(self._embedder_fr, self._vector_store_fr)]
                if (settings.chat_embedding_enabled and self._vector_store_fr is not None)
                else None
            ),
        )

    async def _start_jobs(self):
        from jobs.scheduler import build_scheduler
        from watchers.ged_watcher import GEDWatcher

        self._scheduler = build_scheduler(
            ged_indexer=self._ged_indexer,
            crm_repo=self._crm_repo,
            odoo_sync_interval_hours=settings.odoo_sync_interval_hours,
            container=self,
        )
        self._scheduler.start()

        self._ged_watcher = GEDWatcher(
            ged_path=settings.ged_path,
            ged_indexer=self._ged_indexer,
        )
        self._ged_watcher.start()

    # --- Accesseurs publics (utilisés via FastAPI Depends) ---

    @property
    def llm_haiku(self):
        return self._llm_haiku

    @property
    def llm_sonnet(self):
        return self._llm_sonnet

    @property
    def rag_engine(self):
        return self._rag_engine

    @property
    def presales_vision_ocr(self):
        """DocumentVisionExtractor (adaptateur Claude direct) réutilisé pour transcrire les
        AO scannés côté présale via transcribe_pdf_bytes. None si vision désactivée."""
        return self._vision

    @property
    def rag_engine_fr(self):
        """Moteur RAG FR (CamemBERT) pour le chat + l'inspection documentaire (uc02).
        Identique au moteur legacy si chat_embedding_enabled=False."""
        return self._rag_engine_fr

    @property
    def vector_store_fr(self):
        """Collection ChromaDB FR du chat. Retombe sur la collection legacy si le chat FR
        est désactivé (kill-switch)."""
        return self._vector_store_fr or self._vector_store

    @property
    def query_dispatcher(self):
        return self._query_dispatcher

    @property
    def ged_indexer(self):
        return self._ged_indexer

    @property
    def crm_repo(self):
        return self._crm_repo

    @property
    def token_budget(self):
        return self._token_budget

    @property
    def data_shield(self):
        return self._data_shield

    @property
    def odoo_adapter(self):
        return self._odoo_adapter

    @property
    def doc_registry(self):
        return self._doc_registry

    @property
    def vector_store(self):
        return self._vector_store

    @property
    def reranker(self):
        return self._reranker

    @property
    def pdf_parser(self):
        return self._pdf_parser

    @property
    def docx_parser(self):
        return self._docx_parser

    @property
    def quarantine(self):
        return self._quarantine

    @property
    def kb_repository(self):
        return self._kb_repository

    @property
    def structured_extractor(self):
        return self._structured_extractor

    @property
    def classifier(self):
        return self._classifier

    @property
    def entity_resolver(self):
        return self._entity_resolver

    @property
    def ro_sql(self):
        return self._ro_sql
