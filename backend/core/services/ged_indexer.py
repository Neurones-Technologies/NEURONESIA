import asyncio
import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path

from core.ports.vector_store import VectorStore
from core.ports.sparse_search import SparseSearch
from core.ports.embedder import Embedder
from core.ports.document_registry import DocumentRegistry
from core.ports.document_parser import DocumentParser
from core.domain.document import GEDEntry, DocumentType, DocumentMetadata
from core.services.chunking.router import ChunkingRouter
from core.services.metadata_extractor import MetadataExtractor
from core.services.quality_validator import QualityValidator
from core.services.pii_detector import PIIDetector

logger = logging.getLogger(__name__)

_EMBED_BATCH = 96


class GEDIndexer:
    """
    Pipeline d'indexation incrémentale de la GED.

    Ordre d'exécution :
      1. Hash check (skip si inchangé)
      2. Extraction texte
      3. Validation qualité → quarantaine si rejeté
      4. Extraction métadonnées via LLM (Haiku, tool_use)
      5. Détection PII (CV uniquement)
      6. Chunking adapté au type (ChunkingRouter)
      7. Embedding + upsert ChromaDB
      8. BM25 + registre SQLite
    """

    def __init__(
        self,
        vector_store: VectorStore,
        sparse_search: SparseSearch,
        embedder: Embedder,
        registry: DocumentRegistry,
        pdf_parser: DocumentParser,
        docx_parser: DocumentParser,
        chunking_router: ChunkingRouter,
        metadata_extractor: MetadataExtractor,
        quality_validator: QualityValidator,
        pii_detector: PIIDetector,
        quarantine,  # QuarantineAdapter — import circulaire évité
        structured_extractor=None,  # StructuredExtractor — couche kb_* (optionnel)
        kb_repository=None,         # KBRepository — persistance kb_* (optionnel)
        classifier=None,            # DocumentClassifier — fallback si type UNKNOWN (optionnel)
        entity_resolver=None,       # EntityResolver — résolution d'entités P2 (optionnel)
        vision_extractor=None,      # DocumentVisionExtractor — contenu visuel des pages (optionnel)
        secondary_targets: list[tuple[Embedder, VectorStore]] | None = None,
        chunk_size: int = 600,
        chunk_overlap: int = 60,
    ):
        self._vector_store = vector_store
        self._sparse_search = sparse_search
        self._embedder = embedder
        # Cibles vectorielles (embedder, vector_store) : chaque document est embarqué et
        # upserté dans TOUTES les cibles. La cible primaire est l'historique ; les
        # secondaires (ex. collection FR CamemBERT pour le chat) restent ainsi synchronisées
        # à partir du MÊME texte/chunking. Le BM25 est indexé par chunk_id (identique quel
        # que soit le modèle) → partagé entre toutes les collections, écrit une seule fois.
        self._targets: list[tuple[Embedder, VectorStore]] = [(embedder, vector_store)]
        if secondary_targets:
            self._targets.extend(secondary_targets)
        # Tous les stores (pour les opérations sans embedding : suppression, reset, purge).
        self._stores: list[VectorStore] = [t[1] for t in self._targets]
        self._registry = registry
        self._parsers: list[DocumentParser] = [pdf_parser, docx_parser]
        self._chunking_router = chunking_router
        self._metadata_extractor = metadata_extractor
        self._quality_validator = quality_validator
        self._pii_detector = pii_detector
        self._quarantine = quarantine
        self._structured_extractor = structured_extractor
        self._kb_repository = kb_repository
        self._classifier = classifier
        self._entity_resolver = entity_resolver
        self._vision = vision_extractor
        # Sérialise les passes d'indexation par fichier : un upload déclenche À LA FOIS
        # une tâche de fond immédiate (api/v1/ged.py) ET le watcher filesystem (3 s de
        # debounce) sur le même fichier. Sans verrou, les deux lisent le registre avant
        # que l'une n'ait committé, et la seconde tente un INSERT en double sur
        # file_path (UNIQUE) → IntegrityError. Un verrou par chemin force la seconde
        # passe à attendre la première ; elle retrouve alors un registre à jour (hash
        # identique → skip, ou doc_id correct à réutiliser).
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, file_str: str) -> asyncio.Lock:
        lock = self._locks.get(file_str)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[file_str] = lock
        return lock

    async def process(
        self,
        file_path: Path,
        doc_type: DocumentType = DocumentType.UNKNOWN,
        force: bool = False,
        bypass_validation: bool = False,
    ) -> bool:
        """
        Indexe un fichier si son contenu a changé depuis la dernière indexation.
        Retourne True si indexé, False si ignoré (hash identique ou quarantaine).

        force=True : ré-indexe même si le hash est identique. Indispensable après une
        amélioration du parser (ex. OCR ciblé) ou un changement de stratégie de chunking,
        qui changent le texte extrait sans changer le fichier source.
        bypass_validation=True : trappe d'acceptation manuelle — saute la validation
        qualité (longueur minimale, ratio PDF). Réservé à une action humaine explicite
        depuis la revue de quarantaine, pour accepter un document court mais légitime
        (ex. certification scannée). N'affecte JAMAIS l'ingestion automatique.
        """
        # Normaliser en chemin absolu résolu : le watcher passe des chemins relatifs
        # (../data/ged/...) et le reindex de l'API des chemins absolus. Sans ça, le même
        # fichier est enregistré sous deux clés → indexation en double.
        file_path = Path(file_path).resolve()
        file_str = str(file_path)
        async with self._lock_for(file_str):
            return await self._process_locked(file_path, file_str, doc_type, force, bypass_validation)

    async def _process_locked(
        self,
        file_path: Path,
        file_str: str,
        doc_type: DocumentType,
        force: bool,
        bypass_validation: bool,
    ) -> bool:
        # ── 1. Hash check ──────────────────────────────────────────────────
        current_hash = await asyncio.to_thread(self._compute_hash_sync, file_path)
        existing = await self._registry.get_entry(file_str)
        if existing and existing.hash_sha256 == current_hash and not force:
            logger.debug("Fichier inchangé, skip : %s", file_path.name)
            return False

        # ── 2. Extraction texte ────────────────────────────────────────────
        text = await self._parse(file_path)

        # ── 3. Validation qualité ──────────────────────────────────────────
        validation = self._quality_validator.validate(text, file_path)
        if not validation.is_valid:
            if bypass_validation:
                logger.warning(
                    "Validation qualité ignorée (force_index manuel) pour %s : %s",
                    file_path.name, validation.reason,
                )
            else:
                file_size = self._file_size(file_path)
                await self._quarantine.add(
                    file_path=file_str,
                    doc_type=doc_type.value,
                    reason=validation.reason,
                    file_size_bytes=file_size,
                    text_length=len(text),
                )
                return False

        if validation.warnings:
            for w in validation.warnings:
                logger.warning("QualityValidator [%s] : %s", file_path.name, w)

        # ── 3bis. Classification (fallback si le dossier n'a pas donné le type) ──
        if doc_type == DocumentType.UNKNOWN and self._classifier:
            try:
                doc_type = await self._classifier.classify(text, file_path.name)
                logger.info("Classifieur → %s pour %s", doc_type.value, file_path.name)
            except Exception as exc:
                logger.warning("Classification échouée pour %s : %s", file_path.name, exc)

        # ── 3ter. Contenu VISUEL des pages-images (tous docs) → lecture vision, injecté ──
        # Doit précéder l'extraction (4) et le chunking (7) pour que le champ structuré ET le
        # RAG voient ce que la couche texte/OCR ne restitue pas (schémas, tableaux, badges).
        if self._vision is not None:
            text = await self._augment_with_vision(text, file_path, doc_type)

        # ── 4. Extraction métadonnées ──────────────────────────────────────
        extracted_fields = await self._metadata_extractor.extract(text, doc_type)

        # ── 5. Détection PII ───────────────────────────────────────────────
        pii_report = self._pii_detector.detect(text) if doc_type == DocumentType.CV else None

        # ── 6. Construction des métadonnées du document ───────────────────
        if existing:
            for store in self._stores:
                await store.delete_by_doc_id(existing.doc_id)
            self._sparse_search.remove(existing.vector_ids)
            doc_id = existing.doc_id
        else:
            doc_id = str(uuid.uuid4())

        metadata = DocumentMetadata(
            doc_id=doc_id,
            filename=file_path.name,
            doc_type=doc_type,
            source_path=file_str,
            extracted_fields=extracted_fields,
            contains_pii=pii_report.has_pii if pii_report else False,
            pii_categories=pii_report.categories if pii_report else [],
        )

        # ── 7. Chunking adapté au type ─────────────────────────────────────
        chunks = self._chunking_router.chunk(text, doc_id, metadata)
        if not chunks:
            logger.warning("Aucun chunk généré pour %s", file_path.name)
            return False

        # ── 8. Embeddings par batch → upsert dans CHAQUE cible vectorielle ──
        # Les chunks (ids + contenu) sont identiques pour toutes les cibles ; seul le modèle
        # d'embedding diffère. On ré-embarque donc le même texte par cible (modèles locaux).
        contents = [c.content for c in chunks]
        for embedder, store in self._targets:
            embeddings: list[list[float]] = []
            for i in range(0, len(contents), _EMBED_BATCH):
                batch = contents[i : i + _EMBED_BATCH]
                batch_emb = await embedder.embed_texts(batch)
                embeddings.extend(batch_emb)
            await store.upsert(chunks, embeddings)

        # ── 9. BM25 + registre ─────────────────────────────────────────────
        bm25_chunks = [(c.chunk_id, c.content) for c in chunks]
        await asyncio.to_thread(self._sparse_search.index, bm25_chunks)
        await asyncio.to_thread(self._sparse_search.save)

        entry = GEDEntry(
            doc_id=doc_id,
            file_path=file_str,
            hash_sha256=current_hash,
            doc_type=doc_type,
            last_indexed=datetime.utcnow(),
            vector_ids=[c.chunk_id for c in chunks],
            is_active=True,
        )
        await self._registry.upsert_entry(entry)

        # Retirer de la quarantaine si le fichier y était (ex : retry après correction)
        await self._quarantine.remove(file_str)

        # ── 10. Extraction structurée → base relationnelle kb_* (couche additive) ──
        # Jamais bloquant : un échec ici n'invalide pas l'indexation vectorielle.
        await self._extract_structured(text, doc_type, doc_id, file_str, current_hash)

        # ── 11. Résolution d'entités → ids canoniques (kb_clients/personnes/projets) ──
        await self._resolve_entities(doc_id, doc_type)

        pii_note = f" [PII: {','.join(pii_report.categories)}]" if pii_report and pii_report.has_pii else ""
        logger.info(
            "Indexé : %s → %d chunks (type=%s, doc_id=%s)%s",
            file_path.name, len(chunks), doc_type.value, doc_id, pii_note,
        )
        return True

    async def reset_index(self) -> dict:
        """Vide entièrement l'index (ChromaDB + BM25 + registre) pour une reconstruction à neuf.
        À enchaîner avec une ré-indexation de tous les fichiers du disque."""
        for store in self._stores:
            store.reset()
        self._sparse_search.clear()
        removed = await self._registry.clear_all()
        logger.info("Index GED réinitialisé — %d entrées de registre purgées", removed)
        return {"registry_cleared": removed}

    async def cleanup_orphans(self) -> dict:
        """Purge les chunks orphelins : ceux dont le doc_id n'est plus un document actif du
        registre (séquelles de réindexations passées sous un autre doc_type). Nettoie aussi
        le miroir BM25. Retourne un récapitulatif."""
        entries = await self._registry.list_active_entries()
        valid_doc_ids = {e.doc_id for e in entries}
        orphan_ids_all: set[str] = set()
        for store in self._stores:
            store_orphans = await store.delete_orphans(valid_doc_ids)
            orphan_ids_all.update(store_orphans)
        orphan_ids = list(orphan_ids_all)
        if orphan_ids:
            self._sparse_search.remove(orphan_ids)
            await asyncio.to_thread(self._sparse_search.save)
        logger.info("cleanup_orphans : %d chunks orphelins purgés (%d docs actifs)",
                    len(orphan_ids), len(valid_doc_ids))
        return {"orphans_deleted": len(orphan_ids), "active_docs": len(valid_doc_ids)}

    async def remove(self, file_path: Path, hard_delete: bool = False) -> None:
        """
        Supprime un fichier du RAG (suite à suppression dans la GED).
        hard_delete=True pour les CV (RGPD : purge complète du registre, pas soft-delete).
        """
        file_path = Path(file_path).resolve()
        file_str = str(file_path)
        entry = await self._registry.get_entry(file_str)
        if entry:
            for store in self._stores:
                await store.delete_by_doc_id(entry.doc_id)
            self._sparse_search.remove(entry.vector_ids)
            await asyncio.to_thread(self._sparse_search.save)
            if self._kb_repository:
                try:
                    await self._kb_repository.delete_by_doc_id(entry.doc_id)
                except Exception as exc:
                    logger.warning("Suppression kb_* échouée pour %s : %s", file_path.name, exc)
            if hard_delete:
                await self._registry.hard_delete(file_str)
                logger.info("RGPD — Purge complète : %s", file_path.name)
            else:
                await self._registry.mark_deleted(file_str)
                logger.info("Supprimé du RAG : %s", file_path.name)
        await self._quarantine.remove(file_str)

    async def _extract_structured(
        self, text: str, doc_type: DocumentType, doc_id: str, file_str: str, current_hash: str
    ) -> None:
        """Extraction typée + persistance kb_*. Tolérante aux pannes (best-effort)."""
        if not self._structured_extractor or not self._kb_repository:
            return
        try:
            result = await self._structured_extractor.extract(text, doc_type)
            if result is None:
                return
            await self._kb_repository.save_extraction(
                doc_id=doc_id,
                doc_type=doc_type,
                fichier_source=file_str,
                hash_sha256=current_hash,
                result=result,
            )
        except Exception as exc:
            logger.warning("Extraction structurée échouée pour %s : %s", file_str, exc)

    async def _augment_with_vision(self, text: str, file_path: Path, doc_type: DocumentType) -> str:
        """Lit le contenu visuel des pages-images (schémas, tableaux, badges) et l'injecte :
        le contenu transcrit/décrit est AJOUTÉ en fin de texte (chunké pour le RAG) ; pour les
        CV, les certifications sont aussi PRÉPENDUES (fenêtre de l'extracteur kb_cv = 3000 chars).
        Best-effort : renvoie le texte inchangé en cas d'échec ou si rien n'est trouvé."""
        try:
            res = await self._vision.extract(file_path, doc_type)
        except Exception as exc:
            logger.warning("Extraction vision échouée pour %s : %s", file_path.name, exc)
            return text
        contenu = res.get("contenu") or ""
        certs = res.get("certifications") or []
        out = text
        if contenu:
            out = f"{out}\n\n[CONTENU VISUEL DES PAGES IMAGES]\n{contenu}"
        if doc_type == DocumentType.CV and certs:
            out = "CERTIFICATIONS (extraites des badges) : " + " ; ".join(certs) + "\n\n" + out
            logger.info("CV %s : %d certification(s) injectée(s) depuis les logos", file_path.name, len(certs))
        elif contenu:
            logger.info("%s : contenu visuel injecté (%d chars)", file_path.name, len(contenu))
        return out

    async def _resolve_entities(self, doc_id: str, doc_type: DocumentType) -> None:
        """Résolution d'entités → ids canoniques. Tolérante aux pannes (best-effort)."""
        if not self._entity_resolver or not self._kb_repository:
            return
        try:
            await self._kb_repository.resolve_document(doc_id, doc_type, self._entity_resolver)
        except Exception as exc:
            logger.warning("Résolution d'entités échouée pour %s : %s", doc_id, exc)

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_hash_sync(file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def _file_size(file_path: Path) -> int:
        try:
            return file_path.stat().st_size
        except OSError:
            return 0

    async def _parse(self, file_path: Path) -> str:
        for parser in self._parsers:
            if parser.supports(str(file_path)):
                return await parser.parse(str(file_path))
        if file_path.suffix == ".txt":
            return file_path.read_text(encoding="utf-8", errors="ignore")
        return ""
