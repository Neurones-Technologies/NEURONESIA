import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, desc

from db.database import AsyncSessionLocal
from db.models import VeilleSourceModel, VeilleEntryModel, VeilleConfigModel
from modules.uc_veille.schemas import (
    VeilleSourceCreate, VeilleSourceOut, VeilleEntryOut, VeilleEntryPatch,
    VeilleConfigOut, VeilleConfigPatch,
)
from modules.uc_veille.scanner import scan_rss_feed, scan_html_page, DEMO_SOURCES
from api.v1.dependencies import CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/veille", tags=["Veille AO"])


@router.get("/feed", response_model=list[VeilleEntryOut])
async def get_feed(current_user: CurrentUser, limit: int = 50, status: str = ""):
    async with AsyncSessionLocal() as session:
        q = select(VeilleEntryModel).order_by(desc(VeilleEntryModel.detected_at)).limit(limit)
        if status:
            q = q.where(VeilleEntryModel.status == status)
        result = await session.execute(q)
        return result.scalars().all()


@router.get("/stats")
async def get_stats(current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(VeilleEntryModel))).scalars().all()
        new_count = sum(1 for e in total if e.status == "new")
        return {"total": len(total), "new": new_count}


async def _get_or_create_config(session) -> VeilleConfigModel:
    cfg = await session.get(VeilleConfigModel, 1)
    if cfg is None:
        cfg = VeilleConfigModel(id=1)
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


@router.get("/config", response_model=VeilleConfigOut)
async def get_config(current_user: CurrentUser):
    """Configuration de l'agent : thèmes prioritaires + exploration web."""
    async with AsyncSessionLocal() as session:
        return await _get_or_create_config(session)


@router.put("/config", response_model=VeilleConfigOut)
async def update_config(body: VeilleConfigPatch, current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        cfg = await _get_or_create_config(session)
        if body.themes is not None:
            cfg.themes = body.themes[:2000]
        if body.web_search_enabled is not None:
            cfg.web_search_enabled = body.web_search_enabled
        cfg.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(cfg)
        return cfg


@router.get("/sources", response_model=list[VeilleSourceOut])
async def get_sources(current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(VeilleSourceModel).order_by(VeilleSourceModel.id))
        return result.scalars().all()


@router.post("/sources", response_model=VeilleSourceOut)
async def add_source(body: VeilleSourceCreate, current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        src = VeilleSourceModel(**body.model_dump())
        session.add(src)
        await session.commit()
        await session.refresh(src)
        return src


@router.delete("/sources/{source_id}")
async def delete_source(source_id: int, current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        src = await session.get(VeilleSourceModel, source_id)
        if not src:
            raise HTTPException(404, "Source introuvable")
        await session.delete(src)
        await session.commit()
    return {"ok": True}


@router.patch("/entries/{entry_id}", response_model=VeilleEntryOut)
async def patch_entry(entry_id: int, body: VeilleEntryPatch, current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        entry = await session.get(VeilleEntryModel, entry_id)
        if not entry:
            raise HTTPException(404, "Entrée introuvable")
        if body.status:
            entry.status = body.status
        await session.commit()
        await session.refresh(entry)
        return entry


@router.post("/entries/{entry_id}/pitch")
async def generate_pitch(entry_id: int, request: Request, current_user: CurrentUser):
    """Génère un pitch d'avant-vente par Claude à partir de l'entrée + son analyse S2I."""
    from modules.uc_veille.pitch import build_pitch
    async with AsyncSessionLocal() as session:
        entry = await session.get(VeilleEntryModel, entry_id)
        if not entry:
            raise HTTPException(404, "Entrée introuvable")
    container = getattr(request.app.state, "container", None)
    llm = getattr(container, "llm_sonnet", None) if container is not None else None
    pitch = await build_pitch(llm, entry)
    return {"pitch": pitch}


@router.post("/entries/{entry_id}/debrief")
async def generate_debrief(entry_id: int, current_user: CurrentUser):
    """Génère (Claude lit le lien direct via web_fetch) ET SAUVEGARDE le débriefing
    d'une entrée. Le cas normal est la pré-génération au scan ; cet endpoint sert au
    backfill / rafraîchissement manuel des entrées dont le débriefing est vide."""
    from config.settings import settings
    from adapters.llm.claude_haiku_adapter import ClaudeHaikuAdapter
    from modules.uc_veille.debrief import build_debrief

    async with AsyncSessionLocal() as session:
        entry = await session.get(VeilleEntryModel, entry_id)
        if not entry:
            raise HTTPException(404, "Entrée introuvable")

        # generate_with_url_fetch est additive (hors interface LLMGateway) : instancier
        # un ClaudeHaikuAdapter direct, pas container.llm_haiku qui peut être enveloppé
        # dans un FallbackLLMAdapter sans cette méthode (même raison que l'exploration web).
        llm = ClaudeHaikuAdapter() if settings.veille_ai_enabled else None
        debrief = await build_debrief(llm, entry)
        entry.debrief = debrief
        await session.commit()
    return {"debrief": debrief}


@router.post("/scan")
async def manual_scan(request: Request, current_user: CurrentUser):
    """Déclenche un scan manuel de toutes les sources actives."""
    container = request.app.state.container
    await _run_scan(container)
    return {"ok": True, "message": "Scan terminé"}


@router.post("/init-demo")
async def init_demo_sources(current_user: CurrentUser):
    """Initialise les sources démo si aucune n'existe."""
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(VeilleSourceModel))
        if existing.scalars().first():
            return {"ok": True, "message": "Sources déjà configurées"}
        for src_data in DEMO_SOURCES:
            session.add(VeilleSourceModel(**src_data))
        await session.commit()
    return {"ok": True, "message": f"{len(DEMO_SOURCES)} sources démo ajoutées"}


async def _dedupe(entries: list[dict]) -> list[dict]:
    """Ne garde que les entrées vraiment nouvelles (par URL, sinon par titre)."""
    new_entries: list[dict] = []
    async with AsyncSessionLocal() as session:
        for e in entries:
            if e["url"]:
                exists = (await session.execute(
                    select(VeilleEntryModel.id).where(VeilleEntryModel.url == e["url"])
                )).first()
            elif e["title"]:
                exists = (await session.execute(
                    select(VeilleEntryModel.id).where(VeilleEntryModel.title == e["title"])
                )).first()
            else:
                exists = None
            if not exists:
                new_entries.append(e)
    return new_entries


async def _add_debriefs(web_llm, entries: list[dict], min_crit: int, budget: int) -> int:
    """Pré-génère le débriefing (Claude lit la page réelle via web_fetch) pour les
    entrées éligibles — celles qui ont une URL ET une criticité suffisante, les plus
    critiques d'abord, dans la limite du budget. Écrit le résultat dans e["debrief"]
    et renvoie le budget restant. Concurrence bornée pour limiter la latence du scan.
    """
    from modules.uc_veille.debrief import build_debrief

    if web_llm is None or budget <= 0:
        return budget
    candidates = sorted(
        (e for e in entries if e.get("url") and e.get("criticite", 0) >= min_crit),
        key=lambda e: e.get("criticite", 0),
        reverse=True,
    )[:budget]
    if not candidates:
        return budget

    sem = asyncio.Semaphore(4)  # 4 débriefings en parallèle max (latence vs rate limit)

    async def _one(e: dict):
        async with sem:
            e["debrief"] = await build_debrief(web_llm, SimpleNamespace(**e))

    await asyncio.gather(*(_one(e) for e in candidates))
    logger.info("Débriefings pré-générés : %d", len(candidates))
    return budget - len(candidates)


async def _run_scan(container=None):
    """Scanne les sources actives + explore le web (si activé), classe via Claude,
    insère les nouvelles entrées.

    Pipeline : (1) dédoublonnage en lecture, (2) analyse IA hors transaction DB
    (appels Claude lents), (3) insertion en écriture courte. Budget IA partagé
    entre sources internes et exploration web pour maîtriser le coût par scan.
    """
    from config.settings import settings
    from adapters.llm.claude_haiku_adapter import ClaudeHaikuAdapter
    from modules.uc_veille.classifier import classify_entry
    from modules.uc_veille.web_explorer import explore_web

    llm = getattr(container, "llm_haiku", None) if container is not None else None
    ai_enabled = settings.veille_ai_enabled and llm is not None
    ai_budget = settings.veille_max_ai_entries_per_scan if ai_enabled else 0
    # Débriefings pré-générés au scan (lecture réelle de la page via web_fetch),
    # sauvegardés pour affichage instantané au clic. Budget/seuil séparés du budget IA.
    debrief_budget = settings.veille_max_debrief_per_scan if ai_enabled else 0
    debrief_min_crit = settings.veille_debrief_min_criticite

    # `container.llm_haiku` peut être enveloppé dans un FallbackLLMAdapter (Claude →
    # GPT → Ollama) si settings.llm_fallback_enabled — ce wrapper n'expose PAS la
    # méthode additive generate_with_web_search (spécifique à l'outil serveur
    # Claude). Même convention que la vision (container.py) : instancier un
    # ClaudeHaikuAdapter direct pour cette capacité, indépendamment du wrapper.
    web_llm = ClaudeHaikuAdapter() if ai_enabled else None

    themes, web_search_enabled = "", False
    async with AsyncSessionLocal() as session:
        cfg = await session.get(VeilleConfigModel, 1)
        if cfg:
            themes = cfg.themes
            web_search_enabled = cfg.web_search_enabled
        sources_result = await session.execute(
            select(VeilleSourceModel).where(VeilleSourceModel.active == True)  # noqa: E712 (idiome SQLAlchemy)
        )
        sources = sources_result.scalars().all()

    for source in sources:
        logger.info(f"Scan veille : {source.name}")
        if source.feed_type == "rss":
            entries = await scan_rss_feed(source.url, source.keywords)
        else:
            entries = await scan_html_page(source.url, source.keywords)

        new_entries = await _dedupe(entries)

        # Analyse IA S2I (Claude) — plafonnée, hors transaction, non bloquante.
        for e in new_entries:
            if ai_budget > 0:
                e.update(await classify_entry(llm, e["title"], e["description"], themes))
                ai_budget -= 1

        # Pré-génération des débriefings (page réelle lue au moment de la détection).
        debrief_budget = await _add_debriefs(web_llm, new_entries, debrief_min_crit, debrief_budget)

        async with AsyncSessionLocal() as session:
            for e in new_entries:
                session.add(VeilleEntryModel(source_id=source.id, **e))
            src_obj = await session.get(VeilleSourceModel, source.id)
            if src_obj:
                src_obj.last_scan = datetime.utcnow()
            await session.commit()

        logger.info(f"Scan {source.name} terminé : {len(new_entries)} nouvelle(s) entrée(s)")

    # Exploration web (option « Explorer Internet ») — en plus des sources internes,
    # pas de source_id (aucune VeilleSourceModel associée) ; origin="web" sur chaque entrée.
    if web_search_enabled and ai_enabled and ai_budget > 0:
        logger.info("Exploration web veille (thèmes : %s)", themes[:120] or "(aucun)")
        web_entries = await explore_web(web_llm, themes, max_results=min(ai_budget, 5))
        new_web_entries = await _dedupe(web_entries)
        for e in new_web_entries:
            if ai_budget > 0:
                # classify_entry ne fait que .generate() (interface standard) : le
                # llm partagé (potentiellement fallback) convient très bien ici.
                e.update(await classify_entry(llm, e["title"], e["description"], themes))
                ai_budget -= 1
        # Pré-génération des débriefings pour les entrées web (URL directe = idéal).
        debrief_budget = await _add_debriefs(web_llm, new_web_entries, debrief_min_crit, debrief_budget)
        async with AsyncSessionLocal() as session:
            for e in new_web_entries:
                session.add(VeilleEntryModel(source_id=None, **e))
            await session.commit()
        logger.info("Exploration web terminée : %d nouvelle(s) entrée(s)", len(new_web_entries))
