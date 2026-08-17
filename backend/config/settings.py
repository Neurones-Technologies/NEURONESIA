from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Models
    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    llm_fallback_enabled: bool = True        # bascule auto sur OpenAI si Anthropic tombe
    # Ollama — modèle local (3ème niveau de fallback)
    ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"           # ollama pull llama3.1 (ou mistral-nemo, qwen2.5)
    ollama_timeout_seconds: float = 120.0    # modèles locaux peuvent être lents au premier appel
    # Backend d'embedding : "local" (sentence-transformers, indépendant du quota OpenAI)
    # ou "openai" (text-embedding-3-small). "local" = UN SEUL modèle indexation + requête
    # → évite tout mélange de dimensions (Cause A).
    embedding_backend: str = "local"
    embed_fallback_enabled: bool = True      # bascule sur sentence-transformers si OpenAI indisponible
    embed_fallback_model: str = "paraphrase-multilingual-MiniLM-L12-v2"   # local multilingue (FR), 384d

    # ── Embeddings CamemBERT pour le CHAT + les DOCUMENTS (uc02) uniquement ──────────
    # Architecture DOUBLE COLLECTION : le chat (uc02) interroge une collection ChromaDB
    # dédiée, embarquée avec un modèle FRANCOPHONE NATIF (sentence-camembert). Presale
    # (uc10) et la veille gardent l'embedder/la collection historiques — AUCUN changement
    # de comportement pour eux. Le GEDIndexer indexe chaque document dans LES DEUX
    # collections (2 embedders locaux) pour qu'elles restent synchronisées.
    #   - chat_embedding_enabled=False → kill-switch : le chat retombe sur l'embedder
    #     historique (rag_engine legacy) ; aucune collection FR n'est créée ni interrogée.
    #   - Après activation (ou changement de modèle), réindexer une fois : POST /ged/rebuild
    #     (ou scripts/reindex_all.py) pour peupler la collection FR.
    chat_embedding_enabled: bool = True
    chat_embedding_model: str = "dangvantuan/sentence-camembert-base"   # FR natif, 768d, CPU-friendly
    chat_collection_name: str = "neurones_ged_fr"                       # collection ChromaDB dédiée au chat

    # Odoo (serveur distant)
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_username: str = ""
    odoo_password: str = ""
    odoo_sync_interval_hours: int = 2   # fallback legacy
    odoo_sync_interval_minutes: int = 2  # sync incrémentale rapide
    odoo_webhook_secret: str = ""        # HMAC secret pour les webhooks Odoo

    # ── Partenaires intra-groupe exclus du miroir ────────────────────────────
    # Ni synchronisés depuis Odoo, ni conservés en base locale. Odoo (la source)
    # n'est jamais modifié : ces entités continuent d'y vivre normalement.
    #
    # NEURONES TECHNOLOGIES BF porte DEUX fiches Odoo : client 2671 et
    # fournisseur 3485. Motif de l'exclusion : entité du groupe, dont un seul BDC
    # (FP/2022/6658, saisie erronée à 15,27 Md XOF) représentait 93 % du CA
    # qu'elle portait et écrasait tous les classements client du cockpit.
    #
    # Exclure par ID Odoo et NON par motif de nom : la base compte 10 entités
    # « NEURONES » distinctes (NEURONES TECHNOLOGIES, BENIN, ACADEMY, GROUP,
    # DISTRIBUTIONS, GUINEE, SA…) qu'un LIKE '%NEURONES%' ferait disparaître avec.
    #
    # Ajouter une entité = ajouter son/ses ID ici, puis rejouer la purge :
    #   python -m scripts.purge_partenaires_exclus --apply
    excluded_partner_odoo_ids: set[int] = {2671, 3485}
    # Utilisé pour la SEULE table `dossiers`, qui ne porte pas de client_id mais
    # uniquement un client_name. Comparaison sur le nom exact (insensible à la
    # casse), jamais en sous-chaîne — cf. les 10 entités ci-dessus.
    excluded_partner_names: tuple[str, ...] = ("NEURONES TECHNOLOGIES BF",)

    # Chemins données
    ged_path: Path = Path("../data/ged")
    templates_path: Path = Path("../data/templates")
    uploads_path: Path = Path("../data/uploads")
    chromadb_path: Path = Path("../data/chromadb")
    bm25_index_path: Path = Path("../data/bm25_index")
    local_db_path: Path = Path("../data/local_db/neurones.db")

    # RAG
    chunk_size: int = 600
    chunk_overlap: int = 60
    retrieval_top_k: int = 10
    rerank_top_k: int = 5
    max_context_tokens: int = 10000   # budget contexte RAG (tokens réels) ; Haiku gère 200k, 3000 tronquait les parents
    # Chunks max conservés par fichier après fusion (dédoublonnage). 1 = un seul chunk/doc
    # (max de diversité) mais un CV multi-pages ne remonte alors que sa page la mieux classée
    # → ses certifs (autre page) sont perdues. 2 = recall des docs multi-pages sans noyer le top-k.
    rag_max_chunks_per_file: int = 2
    # Taille d'extrait conservée par chunk (chars). Un chunk fait ~600 mots (~4000-4500 chars) :
    # un excerpt trop court ampute la FIN du chunk — or les certifications d'un CV y vivent
    # (ex. « ODOO Functional Certification » à l'offset 2657 d'un CV de 3112 chars était coupée à
    # 2500). On dimensionne pour tenir un chunk entier → plus de troncature en plein milieu d'une
    # info décisive. Le budget global reste borné par max_context_tokens dans build_context.
    excerpt_chars: int = 4500
    # Levier ① — plancher de similarité cosinus pour le matching CV (étape 3a). C'est un
    # PRÉ-FILTRE LÉGER (enlève le bruit grossier), PAS le filtre de précision : avec le fallback
    # sentence-transformers (cosinus compressés ~0.4-0.6), un seuil trop haut (ex. 0.50) écarte
    # des matches légitimes AVANT que le re-rank LLM (levier ③) puisse les juger. On garde donc
    # bas et on laisse le LLM trancher. Avec text-embedding-3-small (cosinus mieux étalés ~0.3-0.7),
    # ce seuil pourra remonter. 0 = désactivé.
    cv_min_similarity: float = 0.35
    # Levier ③ — re-rank LLM de pertinence par domaine (étape 3a). Après le plancher cosinus,
    # le LLM juge STRICTEMENT si chaque CV correspond à un profil demandé (un CV réseau ≠ besoin
    # dev Odoo) et écarte les hors-sujet que l'embedder seul ne sait pas distinguer. 1 appel/scoring.
    cv_llm_rerank: bool = True
    # Mêmes leviers ①+③ pour les PROJETS similaires (étape 3b, search_diverse) : sans eux, le
    # matching « par type » remonte toujours le top-2 ABE (souvent Cisco/Fortinet) même pour un AO
    # Odoo, et un fallback injecte des docs hors-type/hors-sujet. Le plancher reste BAS (pré-filtre :
    # à 0.50 il éliminait des ABE GED pertinentes — ex. routeur Cisco pour un AO réseau — avant le
    # re-rank). Le re-rank LLM (project_llm_rerank) fait la précision.
    project_min_similarity: float = 0.35
    project_llm_rerank: bool = True
    # Même levier ① pour la recherche GED du chat (rechercher_documents_ged). Sans plancher, le RRF
    # (purement rangé) remplissait toujours ses rerank_top_k places, même quand 1-2 docs seulement
    # étaient vraiment pertinents — il complétait le quota avec des voisins lointains hors-sujet
    # (ex. une ABE PROSUMA pour une question sur la virtualisation). Le plancher cosinus les écarte
    # AVANT la fusion ; les matches BM25 lexicaux exacts restent éligibles. 0 = désactivé.
    ged_min_similarity: float = 0.35
    # Cache disque des analyses /score (1 fichier JSON par AO, nommé par SHA-256). Désactivé en
    # prod : chaque AO écrivait un fichier → saturation disque serveur. False = aucune lecture ni
    # écriture de cache (chaque /score recalcule). Réactivable sans toucher au code.
    score_cache_enabled: bool = False

    # ── UC10 Présale — leviers latence & offre (ISOLÉS au module présale) ─────────
    # Logge la durée des grandes étapes (scoring, stratégie, offre) — « Lot 0 » de mesure.
    presales_perf_log: bool = True
    # Timeout DUR (secondes) par grand appel LLM présale via asyncio.wait_for. 0 = désactivé
    # (comportement actuel). >0 = un appel qui traîne est coupé proprement plutôt que de bloquer.
    presales_llm_timeout_seconds: float = 0.0
    # Purge LRU des caches disque présale (score / stratégie / offre) : garde les N fichiers
    # les plus récents. 0 = pas de purge. Rend `score_cache_enabled=True` sûr en prod.
    presales_cache_max_files: int = 500
    # Cache disque de la stratégie et des sections d'offre par empreinte (même principe que /score).
    presales_strategy_cache_enabled: bool = False
    # Modèle de rédaction des sections d'offre : "haiku" (défaut, rapide) ou "sonnet"
    # (offre plus qualitative / à fort impact, plus lente). Bascule sans toucher au code.
    offer_sections_model: str = "haiku"
    # Modèle de l'ÉTAPE 4 (analyse + notation + recommandation GO/NO-BID). C'est l'étape
    # décisionnelle : on la fait tourner sur "sonnet" (jugement supérieur) plutôt que haiku,
    # alors que l'extraction (étapes 1/1b, tâche mécanique) reste sur haiku. "haiku" ramène
    # tout le pipeline sur le modèle rapide. Bascule sans toucher au code.
    presales_analysis_model: str = "sonnet"
    # Pré-statut de conformité IA des exigences au moment de l'export/assess de la matrice.
    matrix_assess_on_export: bool = True
    # Taille max (Mo) d'un AO uploadé (endpoints /presales/score et /presales/dossiers).
    # Relevée de 10 à 25 pour accepter les AO SCANNÉS (22 pages en images ≈ 15-30 Mo).
    # Ajustable via .env (PRESALES_MAX_UPLOAD_MB) sans toucher au code.
    presales_max_upload_mb: int = 25

    # OCR PDF
    # tessdata local au projet (eng+osd+fra) — permet d'ajouter le pack FR sans droits admin
    # sur C:\Program Files\Tesseract-OCR\tessdata. Si le dossier existe et contient des
    # *.traineddata, le parser pose TESSDATA_PREFIX dessus → OCR « fra+eng ». Vide/inexistant
    # → Tesseract utilise le tessdata système (eng seul ici).
    tessdata_dir: Path = Path("../data/tessdata")
    ocr_max_pages: int = 40              # cap pages OCR (perf) — au-delà, WARNING explicite
    ocr_min_chars_per_page: int = 80     # en-dessous, la couche texte est jugée trop maigre → OCR
    # Page avec une image significative (certif/diplôme scanné) ET peu de texte → OCR ciblé,
    # même si la couche texte dépasse ocr_min_chars_per_page (cas du titre « Certifications »
    # suivi d'une image). Évite de perdre les pages-image noyées dans un document textuel.
    ocr_image_page_text_max: int = 600   # plafond texte pour déclencher l'OCR d'une page-image
    ocr_image_area_ratio: float = 0.06   # image couvrant ≥ 6 % de la page = significative
                                         # (sépare nettement logos ~1 % des scans de certifs ~9 %+)

    # Extraction structurée (couche kb_*) — Phase 1
    extraction_confidence_threshold: float = 0.6   # sous ce score → revue_humaine=True
    structured_extract_text_limit: int = 8000       # nb de caractères envoyés au LLM

    # Vision — pages porteuses d'IMAGES (tous types de docs). Un LLM multimodal (Haiku) rend
    # la page en image et TRANSCRIT le texte + DÉCRIT schémas/tableaux/logos/badges, que ni la
    # couche texte ni l'OCR ne restituent. Déclenché quand une page a des images couvrant
    # ≥ vision_area_ratio de sa surface (ou une page de CV titrée « certifications »).
    # Borné à vision_max_pages pages/doc → 1 appel vision/doc max. False = désactivé.
    vision_enabled: bool = True
    vision_max_pages: int = 3          # plafond de pages-image analysées par document (coût)
    vision_area_ratio: float = 0.15    # part de surface en image pour déclencher la vision
    vision_dpi: int = 150              # résolution de rendu des pages (lisibilité vs poids)

    # Résolution d'entités (Phase 2)
    entity_match_auto_threshold: float = 0.90       # ≥ → lien automatique
    entity_match_review_threshold: float = 0.75      # [review, auto[ → revue humaine

    # Text-to-SQL lecture seule (Phase 3)
    sql_query_timeout_seconds: float = 8.0           # timeout applicatif d'une requête générée

    # Reranker (P6) — cross-encoder local optionnel après la fusion RRF
    rerank_enabled: bool = False     # si True, le chat re-classe par défaut
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 20      # nb de candidats RRF re-scorés par le cross-encoder

    # Chat
    max_history_turns: int = 6

    # Budget tokens
    token_budget_monthly_fcfa: int = 130_000
    token_alert_threshold_pct: int = 80

    # Quarantaine — auto-suppression des fichiers non indexables (ex. PDF scannés
    # sans texte) après N jours d'inactivité. 0 = désactivé.
    quarantine_retention_days: int = 7

    # Veille AO / Watch-Tracker — agent d'analyse S2I (signal → risque → offre)
    veille_ai_enabled: bool = True            # kill-switch : False → scan mots-clés seul (pas de Claude)
    veille_max_ai_entries_per_scan: int = 30  # plafond d'appels Claude par scan (maîtrise coût/latence)
    # Débriefing pré-généré au scan (Claude lit la page réelle via web_fetch et sauvegarde).
    veille_debrief_min_criticite: int = 40    # criticité min pour pré-générer un débriefing
    veille_max_debrief_per_scan: int = 12     # plafond de débriefings pré-générés par scan (0 = off)

    # Cache
    redis_url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 3600

    # Auth JWT
    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 12

    # CORS — liste séparée par des virgules dans .env
    allowed_origins: str = "http://localhost:3000,http://localhost:3001"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    app_name: str = "Neurones IA"
    app_version: str = "0.1.0"


settings = Settings()
