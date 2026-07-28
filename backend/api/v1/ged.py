import logging
import mimetypes
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config.settings import settings
from core.domain.document import DocumentType

logger = logging.getLogger(__name__)

router = APIRouter()

_TYPE_MAP: dict[str, dict] = {
    "cvs":               {"label": "CVs Ingénieurs",       "doc_type": DocumentType.CV},
    "offres-techniques": {"label": "Offres Techniques",     "doc_type": DocumentType.OFFRE_TECHNIQUE},
    "abe":               {"label": "ABE / Marchés publics", "doc_type": DocumentType.ABE},
    "pv-recette":        {"label": "PV de Recette",         "doc_type": DocumentType.PV_RECETTE},
    "procedures":        {"label": "Procédures internes",   "doc_type": DocumentType.PROCEDURE},
    "fiches-techniques": {"label": "Fiches Techniques",     "doc_type": DocumentType.FICHE_TECHNIQUE},
    "comptes-rendus":    {"label": "Comptes Rendus",        "doc_type": DocumentType.COMPTE_RENDU},
}

_SUPPORTED_EXT = {".pdf", ".docx", ".doc", ".txt"}
_GED_ROOT = Path(settings.ged_path)


def _container(request: Request):
    return request.app.state.container


def _safe_resolve(rel_path: str) -> Path:
    """Résout un chemin relatif et vérifie qu'il reste dans la GED. Lève 400 sinon."""
    try:
        resolved = (_GED_ROOT / rel_path).resolve()
        resolved.relative_to(_GED_ROOT.resolve())
        return resolved
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=400, detail="Chemin invalide ou hors de la GED")


def _safe_filename(name: str) -> str:
    """Neutralise tout séparateur/chemin dans un nom de fichier fourni par le
    client (`UploadFile.filename` n'est pas fiable — un `../../etc/x` ou un
    chemin absolu y écraserait `target_dir` sans cette normalisation)."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    ascii_name = Path(ascii_name).name  # ne garde que le composant final
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("_. ")
    return ascii_name or "document"


def _build_subtree(folder: Path, rel: str) -> dict:
    file_count = 0
    subfolders = []
    if folder.exists():
        for item in sorted(folder.iterdir()):
            if item.is_dir():
                sub_rel = f"{rel}/{item.name}"
                sub = _build_subtree(item, sub_rel)
                subfolders.append(sub)
                file_count += sub["file_count"]
            elif item.is_file() and item.suffix.lower() in _SUPPORTED_EXT:
                file_count += 1
    return {"path": rel, "name": folder.name, "file_count": file_count, "subfolders": subfolders}


# ── GET /ged/tree ─────────────────────────────────────────────────────────────

@router.get("/ged/tree")
async def get_tree():
    """Arbre de dossiers GED avec comptage de fichiers par nœud."""
    _GED_ROOT.mkdir(parents=True, exist_ok=True)
    # Créer les catégories par défaut si elles n'existent pas
    for folder_name in _TYPE_MAP:
        (_GED_ROOT / folder_name).mkdir(parents=True, exist_ok=True)

    categories = []
    for folder_path in sorted(_GED_ROOT.iterdir()):
        if not folder_path.is_dir():
            continue
        folder_name = folder_path.name
        meta = _TYPE_MAP.get(folder_name, {})
        tree = _build_subtree(folder_path, folder_name)
        categories.append({
            "name": folder_name,
            "label": meta.get("label", folder_name.replace("-", " ").title()),
            "doc_type": meta.get("doc_type", DocumentType.UNKNOWN).value,
            "file_count": tree["file_count"],
            "subfolders": tree["subfolders"],
        })
    return {"categories": categories}


# ── GET /ged/status ───────────────────────────────────────────────────────────

@router.get("/ged/status")
async def get_status(request: Request):
    """Stats GED : fichiers indexés, total disque, répartition par type."""
    registry = _container(request).doc_registry
    entries = await registry.list_active_entries()

    by_type: dict[str, int] = {}
    last_indexed_at = None
    for e in entries:
        by_type[e.doc_type.value] = by_type.get(e.doc_type.value, 0) + 1
        if last_indexed_at is None or e.last_indexed > last_indexed_at:
            last_indexed_at = e.last_indexed

    total_on_disk = sum(
        1
        for folder_name in _TYPE_MAP
        for f in (_GED_ROOT / folder_name).rglob("*")
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXT
        if (_GED_ROOT / folder_name).exists()
    )

    return {
        "total_indexed": len(entries),
        "total_on_disk": total_on_disk,
        "by_type": by_type,
        "last_indexed_at": last_indexed_at.isoformat() if last_indexed_at else None,
    }


# ── GET /ged/files ────────────────────────────────────────────────────────────

@router.get("/ged/files")
async def list_files(
    request: Request,
    folder: Optional[str] = None,
    search: Optional[str] = None,
):
    """Liste les fichiers GED. Combine les entrées indexées (registry) et les fichiers disque non encore indexés."""
    registry = _container(request).doc_registry
    entries = await registry.list_active_entries()

    # Toujours travailler avec des chemins absolus résolus pour éviter les
    # incompatibilités entre le chemin relatif _GED_ROOT et les chemins absolus
    # stockés dans le registry (par _safe_resolve → .resolve()).
    ged_root_abs = _GED_ROOT.resolve()

    # Index par chemin relatif normalisé (séparateurs forward slash)
    indexed_by_relpath: dict[str, dict] = {}
    for e in entries:
        try:
            rel = Path(e.file_path).resolve().relative_to(ged_root_abs)
            key = str(rel).replace("\\", "/")
            indexed_by_relpath[key] = {
                "doc_id": e.doc_id,
                "last_indexed": e.last_indexed.isoformat(),
                "is_indexed": True,
            }
        except ValueError:
            pass

    result = []

    # Walk filesystem — tous les dossiers racine présents dans la GED
    all_root_dirs = [p.name for p in ged_root_abs.iterdir() if p.is_dir()] if ged_root_abs.exists() else []
    for folder_name in all_root_dirs:
        root = ged_root_abs / folder_name
        if not root.exists():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in _SUPPORTED_EXT:
                continue
            try:
                rel = f.relative_to(ged_root_abs)
            except ValueError:
                continue
            rel_str = str(rel).replace("\\", "/")
            folder_rel = str(rel.parent).replace("\\", "/") if str(rel.parent) != "." else folder_name

            # Filtre par dossier
            if folder:
                folder_clean = folder.rstrip("/")
                if rel_str != f"{folder_clean}/{f.name}" and not rel_str.startswith(folder_clean + "/"):
                    if rel_str.split("/")[0] != folder_clean:
                        continue

            # Filtre par recherche texte
            if search and search.lower() not in f.name.lower():
                continue

            registry_info = indexed_by_relpath.get(rel_str)

            try:
                size_bytes = f.stat().st_size
            except OSError:
                size_bytes = 0

            result.append({
                "doc_id": registry_info["doc_id"] if registry_info else None,
                "filename": f.name,
                "file_path": rel_str,
                "folder_path": folder_rel,
                "category": folder_name,
                "doc_type": _TYPE_MAP.get(folder_name, {}).get("doc_type", DocumentType.UNKNOWN).value,
                "size_bytes": size_bytes,
                "last_indexed": registry_info["last_indexed"] if registry_info else None,
                "is_indexed": bool(registry_info),
            })

    return {"files": result, "total": len(result)}


# ── GET /ged/documents/{doc_id}/chunks ────────────────────────────────────────

def _extracted_fields_from_meta(meta: dict) -> dict:
    """Reconstruit extracted_fields depuis les clés aplaties ef_* (JSON décodé si besoin)."""
    import json
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


@router.get("/ged/documents/{doc_id}/chunks")
async def get_document_chunks(doc_id: str, request: Request):
    """Détail du découpage d'un document : liste de ses chunks + métadonnées extraites."""
    vector_store = _container(request).vector_store
    items = await vector_store.get_chunks_by_doc_id(doc_id)
    if not items:
        raise HTTPException(status_code=404, detail="Aucun chunk trouvé pour ce document")

    first_meta = items[0]["metadata"]
    chunks = []
    for it in items:
        meta = it["metadata"]
        content = it["content"] or ""
        chunks.append({
            "chunk_id": it["chunk_id"],
            "chunk_index": meta.get("chunk_index", 0),
            "is_parent": bool(meta.get("is_parent", False)),
            "parent_chunk_id": meta.get("parent_chunk_id") or None,
            "word_count": len(content.split()),
            "char_count": len(content),
            "content": content,
        })

    return {
        "doc_id": doc_id,
        "filename": first_meta.get("filename", "?"),
        "doc_type": first_meta.get("doc_type", "unknown"),
        "contains_pii": bool(first_meta.get("contains_pii", False)),
        "chunk_count": len(chunks),
        "extracted_fields": _extracted_fields_from_meta(first_meta),
        "chunks": chunks,
    }


# ── POST /ged/search-debug ────────────────────────────────────────────────────

class SearchDebugRequest(BaseModel):
    query: str
    top_k: int = 10
    doc_type: Optional[str] = None
    rerank: Optional[bool] = None


@router.post("/ged/search-debug")
async def search_debug(body: SearchDebugRequest, request: Request):
    """Playground d'inspection du retrieval : scores dense / BM25 / RRF par chunk, sans dédup."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Requête vide")
    # Inspection alignée sur ce que le chat consomme → moteur FR (CamemBERT).
    rag_engine = _container(request).rag_engine_fr
    return await rag_engine.search_debug(
        query=body.query,
        top_k=max(1, min(body.top_k, 50)),
        doc_type=body.doc_type,
    )


@router.post("/ged/search-prod")
async def search_prod(body: SearchDebugRequest, request: Request):
    """Recherche de PRODUCTION (telle que le chat la consomme) : fusion chunk-level,
    expansion parent (small-to-big) et dédup par parent. Montre les blocs réellement
    injectés au LLM — contrairement à /search-debug qui montre la fusion brute."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Requête vide")
    container = _container(request)
    # Recherche de PRODUCTION telle que le chat la consomme → moteur FR (CamemBERT).
    rag_engine = container.rag_engine_fr
    token_budget = container.token_budget
    filt = {"doc_type": body.doc_type} if body.doc_type else None

    rerank_requested = bool(body.rerank)
    reranker_available = container.reranker is not None
    rerank_applied = rerank_requested and reranker_available

    sources = await rag_engine.search(
        query=body.query,
        filter_metadata=filt,
        top_k=max(1, min(body.top_k, 50)),
        rerank=body.rerank,
    )

    def _tokens(text: str) -> int:
        try:
            return token_budget.estimate_tokens(text)
        except Exception:
            return len((text or "").split())

    return {
        "query": body.query,
        "doc_type": body.doc_type,
        "count": len(sources),
        "rerank_requested": rerank_requested,
        "reranker_available": reranker_available,
        "rerank_applied": rerank_applied,
        "score_label": "rerank" if rerank_applied else "RRF",
        "results": [
            {
                "chunk_id": s.chunk_id,
                "doc_id": s.doc_id,
                "filename": s.filename,
                "doc_type": s.doc_type.value,
                "relevance_score": round(s.relevance_score, 6),
                "expanded_from_parent": s.parent_chunk_id is not None,
                "parent_chunk_id": s.parent_chunk_id,
                "excerpt": s.excerpt,
                "context_words": len((s.content or "").split()),
                "context_tokens": _tokens(s.content or ""),
                "context_chars": len(s.content or ""),
                "context_preview": (s.content or "")[:700],
            }
            for s in sources
        ],
    }


# ── GET /ged/index-health ─────────────────────────────────────────────────────

@router.get("/ged/index-health")
async def index_health(request: Request):
    """Métriques de santé de l'index vectoriel + détection d'anomalies (orphelins)."""
    # Santé de la collection que le chat interroge → collection FR (CamemBERT).
    vector_store = _container(request).vector_store_fr
    registry = _container(request).doc_registry

    stats = await vector_store.get_index_stats()
    entries = await registry.list_active_entries()

    registry_ids = {e.doc_id for e in entries}
    indexed_ids = set(stats.pop("indexed_doc_ids", []))

    # Anomalies : présent au registre mais 0 chunk vectoriel (et inversement)
    filename_by_id = {e.doc_id: Path(e.file_path).name for e in entries}
    orphans_registry = [
        {"doc_id": did, "filename": filename_by_id.get(did, "?")}
        for did in (registry_ids - indexed_ids)
    ]
    orphans_vector = list(indexed_ids - registry_ids)

    stats["registry_documents"] = len(registry_ids)
    stats["anomalies"] = {
        "in_registry_without_chunks": orphans_registry,
        "in_vector_without_registry": orphans_vector,
    }
    return stats


# ── POST /ged/upload ──────────────────────────────────────────────────────────

@router.post("/ged/upload", status_code=201)
async def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder_path: str = Form(...),
):
    """Upload un fichier dans la GED et lance l'indexation en arrière-plan."""
    safe_name = _safe_filename(file.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _SUPPORTED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté : {suffix}. Acceptés : PDF, DOCX, DOC, TXT",
        )

    parts = Path(folder_path).parts
    if not parts:
        raise HTTPException(status_code=400, detail="Chemin de dossier invalide")

    target_dir = _safe_resolve(folder_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    dest = target_dir / safe_name
    dest.write_bytes(content)

    doc_type: DocumentType = _TYPE_MAP.get(parts[0], {}).get("doc_type", DocumentType.UNKNOWN)
    ged_indexer = _container(request).ged_indexer
    background_tasks.add_task(_index_file, ged_indexer, dest, doc_type)

    logger.info("Upload GED : %s → %s", file.filename, dest)
    return {
        "filename": safe_name,
        "folder_path": folder_path,
        "doc_type": doc_type.value,
        "size_bytes": len(content),
        "status": "indexing",
    }


async def _index_file(
    ged_indexer,
    file_path: Path,
    doc_type: DocumentType,
    force: bool = False,
    bypass_validation: bool = False,
):
    try:
        indexed = await ged_indexer.process(
            file_path, doc_type, force=force, bypass_validation=bypass_validation
        )
        logger.info("Indexation %s : %s", file_path.name, "OK" if indexed else "ignoré (inchangé)")
    except Exception as e:
        logger.error("Erreur indexation %s : %s", file_path.name, e)


# ── GET /ged/quarantine ───────────────────────────────────────────────────────

@router.get("/ged/quarantine")
async def list_quarantine(request: Request):
    """Fichiers rejetés par le validateur qualité — en attente de correction."""
    quarantine = _container(request).quarantine
    entries = await quarantine.list_all()
    return {
        "quarantine": [
            {
                "id": e.id,
                "filename": Path(e.file_path).name,
                "file_path": e.file_path,
                "doc_type": e.doc_type,
                "reason": e.reason,
                "quarantined_at": e.quarantined_at.isoformat(),
                "retry_count": e.retry_count,
                "file_size_bytes": e.file_size_bytes,
                "text_length": e.text_length,
            }
            for e in entries
        ],
        "total": len(entries),
        "retention_days": settings.quarantine_retention_days,
    }


# ── DELETE /ged/quarantine ─────────────────────────────────────────────────────

@router.delete("/ged/quarantine")
async def delete_quarantine(file_path: str, request: Request):
    """Supprime un fichier en quarantaine : le fichier sur disque + son enregistrement.
    Utile pour les documents non indexables (ex. PDF scannés sans texte)."""
    path = Path(file_path)
    # Sécurité : le fichier doit rester dans la GED
    try:
        path.resolve().relative_to(_GED_ROOT.resolve())
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=400, detail="Chemin invalide ou hors de la GED")

    quarantine = _container(request).quarantine
    deleted_file = False
    if path.exists():
        try:
            path.unlink()
            deleted_file = True
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Suppression impossible : {e}")
    removed = await quarantine.remove_resolved(file_path)
    logger.info("Quarantaine supprimée : %s (fichier supprimé=%s, %d entrée(s))", path.name, deleted_file, removed)
    return {"deleted": True, "file_path": file_path, "file_removed": deleted_file, "entries_removed": removed}


# ── POST /ged/quarantine/retry ─────────────────────────────────────────────────

class RetryRequest(BaseModel):
    file_path: str
    # Trappe d'acceptation manuelle : accepte le document malgré l'échec de validation
    # qualité (texte trop court, ratio PDF). À n'activer qu'après revue humaine — ex.
    # une certification scannée légitimement courte. Les seuils restent inchangés pour
    # l'ingestion automatique.
    force_index: bool = False


@router.post("/ged/quarantine/retry")
async def retry_quarantine(
    body: RetryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Retente l'indexation d'un fichier en quarantaine.

    Avec force_index=True, la validation qualité est ignorée (acceptation manuelle).
    """
    path = Path(body.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le disque")

    parts = path.parts
    folder_name = next((p for p in parts if p in _TYPE_MAP), None)
    doc_type = _TYPE_MAP.get(folder_name, {}).get("doc_type", DocumentType.UNKNOWN) if folder_name else DocumentType.UNKNOWN
    ged_indexer = _container(request).ged_indexer
    background_tasks.add_task(
        _index_file, ged_indexer, path, doc_type,
        force=body.force_index, bypass_validation=body.force_index,
    )
    return {"status": "retrying", "file_path": body.file_path, "force_index": body.force_index}


# ── GET /ged/files/meta ───────────────────────────────────────────────────────

@router.get("/ged/files/meta")
async def files_meta(ids: str, request: Request):
    """Métadonnées légères (taille, date d'indexation) pour un lot de doc_id — alimente
    les colonnes Taille/Date des tableaux de documents matchés (ex: Projets similaires
    en avant-vente) sans reservir le fichier lui-même."""
    doc_ids = {i.strip() for i in ids.split(",") if i.strip()}
    result: dict[str, dict] = {}
    if not doc_ids:
        return {"files": result}

    registry = _container(request).doc_registry
    entries = await registry.list_active_entries()
    for e in entries:
        if e.doc_id not in doc_ids:
            continue
        try:
            size_bytes = Path(e.file_path).stat().st_size
        except OSError:
            size_bytes = None
        result[e.doc_id] = {
            "size_bytes": size_bytes,
            "last_indexed": e.last_indexed.isoformat() if e.last_indexed else None,
        }
    return {"files": result}


# ── GET /ged/files/{doc_id}/download ──────────────────────────────────────────

def _content_disposition(filename: str, inline: bool) -> str:
    """Content-Disposition robuste : Starlette encode les en-têtes en latin-1, donc un
    accent/espace/— dans le nom ferait crasher la réponse. On donne un nom ASCII de repli
    en filename= ET le nom UTF-8 complet en filename* (RFC 5987) pour le navigateur."""
    disposition = "inline" if inline else "attachment"
    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode()
        .replace('"', "'")
        .strip()
    ) or "document"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/ged/files/{doc_id}/download")
async def download_file(doc_id: str, request: Request, inline: bool = False):
    """Sert le fichier source d'un document GED.
    inline=False (défaut) → téléchargement (attachment) ; inline=True → affichage dans le
    navigateur (aperçu PDF). Auth + garde anti-traversée (chemin sous la racine GED)."""
    registry = _container(request).doc_registry
    entries = await registry.list_active_entries()
    entry = next((e for e in entries if e.doc_id == doc_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Document introuvable")

    file_path = Path(entry.file_path).resolve()
    # Garde anti-traversée : le fichier servi DOIT rester sous la racine GED.
    try:
        file_path.relative_to(_GED_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Chemin hors de la GED")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier absent du disque")

    media_type, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(
        path=str(file_path),
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(file_path.name, inline)},
    )


# ── DELETE /ged/files/{doc_id} ────────────────────────────────────────────────

@router.delete("/ged/files/{doc_id}")
async def delete_file(doc_id: str, request: Request):
    """Supprime un fichier de la GED (disque + index vectoriel + registre)."""
    registry = _container(request).doc_registry
    ged_indexer = _container(request).ged_indexer

    entries = await registry.list_active_entries()
    entry = next((e for e in entries if e.doc_id == doc_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Document introuvable")

    file_path = Path(entry.file_path)
    # RGPD : hard delete pour les CV (purge complète du registre, pas soft-delete)
    hard_delete = entry.doc_type.value == "cv"
    await ged_indexer.remove(file_path, hard_delete=hard_delete)

    if file_path.exists():
        file_path.unlink()

    logger.info("Fichier supprimé de la GED : %s (hard_delete=%s)", file_path.name, hard_delete)
    return {"deleted": True, "doc_id": doc_id, "filename": file_path.name}


# ── POST /ged/folders ─────────────────────────────────────────────────────────

class FolderRequest(BaseModel):
    path: str


@router.post("/ged/folders", status_code=201)
async def create_folder(body: FolderRequest):
    """Crée un dossier, un sous-dossier, ou une nouvelle catégorie racine dans la GED."""
    parts = Path(body.path).parts
    if not parts:
        raise HTTPException(status_code=400, detail="Chemin invalide")
    target = _safe_resolve(body.path)
    target.mkdir(parents=True, exist_ok=True)
    return {"path": body.path, "created": True}


@router.post("/ged/rebuild")
async def rebuild_index(request: Request, background_tasks: BackgroundTasks):
    """Reconstruction à neuf : vide ChromaDB + BM25 + registre, puis ré-indexe tous les
    fichiers réellement présents sur le disque (OCR + embeddings). Élimine d'un coup les
    chunks orphelins, les entrées de registre périmées et les variantes de chemin accumulées."""
    ged_indexer = _container(request).ged_indexer
    ged_root_abs = _GED_ROOT.resolve()

    reset = await ged_indexer.reset_index()

    pending = []
    for folder_name, meta in _TYPE_MAP.items():
        root = ged_root_abs / folder_name
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in _SUPPORTED_EXT:
                pending.append((f, meta["doc_type"]))

    for file_path, doc_type in pending:
        background_tasks.add_task(_index_file, ged_indexer, file_path, doc_type, True)

    return {
        "reset": reset,
        "queued": len(pending),
        "message": f"Reconstruction à neuf : {len(pending)} fichier(s) en file d'indexation",
    }


@router.post("/ged/cleanup-orphans")
async def cleanup_orphans(request: Request):
    """Purge les chunks orphelins (doc_id absent du registre) de ChromaDB + BM25.
    Utile après des réindexations passées ayant laissé un même fichier sous plusieurs doc_types."""
    ged_indexer = _container(request).ged_indexer
    result = await ged_indexer.cleanup_orphans()
    return result


def _doc_type_for(file_path: Path, ged_root_abs: Path) -> DocumentType:
    """Déduit le doc_type d'un fichier depuis son dossier racine sous la GED."""
    try:
        rel = file_path.resolve().relative_to(ged_root_abs)
        top = rel.parts[0] if rel.parts else ""
        meta = _TYPE_MAP.get(top)
        return meta["doc_type"] if meta else DocumentType.UNKNOWN
    except (ValueError, RuntimeError):
        return DocumentType.UNKNOWN


@router.post("/ged/reindex")
async def reindex_all(
    request: Request,
    background_tasks: BackgroundTasks,
    force: bool = False,
    path: Optional[str] = None,
):
    """Relance l'indexation des fichiers GED.

    - défaut : seulement les fichiers non encore indexés.
    - force=true : ré-indexe TOUS les fichiers (à appliquer après une amélioration du parser,
      ex. OCR ciblé des certifs en image — le contenu extrait change sans que le fichier change).
    - path=<chemin relatif> : ne (ré-)indexe que ce fichier (implique force).
    """
    ged_indexer = _container(request).ged_indexer
    ged_root_abs = _GED_ROOT.resolve()

    # Ciblage d'un seul fichier
    if path:
        target = _safe_resolve(path)
        if not target.is_file() or target.suffix.lower() not in _SUPPORTED_EXT:
            raise HTTPException(status_code=404, detail="Fichier introuvable ou non supporté")
        doc_type = _doc_type_for(target, ged_root_abs)
        background_tasks.add_task(_index_file, ged_indexer, target, doc_type, True)
        return {"queued": 1, "force": True, "message": f"Ré-indexation de {target.name} en file"}

    registry = _container(request).doc_registry
    entries = await registry.list_active_entries()
    indexed_paths = {str(Path(e.file_path).resolve()) for e in entries}

    pending = []
    for folder_name, meta in _TYPE_MAP.items():
        root = ged_root_abs / folder_name
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in _SUPPORTED_EXT:
                # force → tout ; sinon seulement ce qui n'est pas déjà indexé
                if force or str(f.resolve()) not in indexed_paths:
                    pending.append((f, meta["doc_type"]))

    for file_path, doc_type in pending:
        background_tasks.add_task(_index_file, ged_indexer, file_path, doc_type, force)

    verb = "ré-indexation complète" if force else "indexation"
    return {
        "queued": len(pending),
        "force": force,
        "message": f"{len(pending)} fichier(s) en file de {verb}",
    }


@router.delete("/ged/folders")
async def delete_folder(path: str, request: Request):
    """Supprime un dossier et tout son contenu (désindexation incluse). Les catégories système ne peuvent pas être supprimées."""
    parts = Path(path).parts
    if len(parts) <= 1 and path in _TYPE_MAP:
        raise HTTPException(status_code=400, detail="Les catégories système ne peuvent pas être supprimées")
    if len(parts) == 0:
        raise HTTPException(status_code=400, detail="Chemin invalide")

    target = _safe_resolve(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Dossier introuvable")

    # Désindexer tous les fichiers contenus dans ce dossier
    registry = _container(request).doc_registry
    ged_indexer = _container(request).ged_indexer
    entries = await registry.list_active_entries()
    target_resolved = target.resolve()
    removed_count = 0
    for e in entries:
        try:
            entry_path = Path(e.file_path).resolve()
            entry_path.relative_to(target_resolved)
            await ged_indexer.remove(entry_path)
            removed_count += 1
        except ValueError:
            pass
        except Exception as ex:
            logger.warning("Erreur désindexation %s : %s", e.file_path, ex)

    shutil.rmtree(target)
    logger.info("Dossier supprimé : %s (%d fichier(s) désindexé(s))", path, removed_count)
    return {"deleted": True, "path": path, "files_deindexed": removed_count}
