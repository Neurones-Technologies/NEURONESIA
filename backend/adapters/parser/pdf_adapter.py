import asyncio
import concurrent.futures
import io
import logging
import os
import platform
import sys
import tempfile
from pathlib import Path

import pdfplumber

from config.settings import settings
from core.ports.document_parser import DocumentParser
from adapters.parser.markdown_fidelity import (
    alnum_count as _alnum_count,
    is_faithful as _is_faithful,
    FIDELITY_MIN_RATIO as _FIDELITY_MIN_RATIO,
    FIDELITY_MIN_BASELINE as _FIDELITY_MIN_BASELINE,
)

logger = logging.getLogger(__name__)

# ── Optional deps ──────────────────────────────────────────────────────────────

_FITZ_AVAILABLE = False
try:
    import fitz  # PyMuPDF  # noqa: F401 (probe de disponibilité)
    _FITZ_AVAILABLE = True
except ImportError:
    pass

_PYMUPDF4LLM_AVAILABLE = False
try:
    import pymupdf4llm  # PDF → Markdown (titres, tableaux, listes) ; s'appuie sur PyMuPDF  # noqa: F401
    _PYMUPDF4LLM_AVAILABLE = True
except ImportError:
    pass

_TESSERACT_AVAILABLE = False
# Langues OCR réellement disponibles, déterminées après détection du binaire.
# On ne demande jamais une langue absente : Tesseract n'échoue pas toujours sur
# "fra+eng" quand "fra" manque (il retombe silencieusement sur "eng"), donc le
# repli via except ne suffit pas à garantir le bon modèle.
_OCR_LANGS = "eng"
try:
    import pytesseract
    from PIL import Image  # noqa: F401 (probe de disponibilité)

    # Sur Windows, pointer vers le chemin par défaut si pas configuré
    if platform.system() == "Windows":
        _win_path = os.environ.get(
            "TESSERACT_CMD",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        )
        if os.path.exists(_win_path):
            pytesseract.pytesseract.tesseract_cmd = _win_path
            _TESSERACT_AVAILABLE = True
        else:
            logger.warning(
                "Tesseract introuvable à %s — OCR désactivé. "
                "Téléchargez l'installer sur https://github.com/UB-Mannheim/tesseract/wiki",
                _win_path,
            )
    else:
        _TESSERACT_AVAILABLE = True

    if _TESSERACT_AVAILABLE:
        # tessdata local au projet (data/tessdata) → ajoute le pack 'fra' sans droits admin
        # sur Program Files. DOIT être posé AVANT get_languages/OCR pour être pris en compte.
        try:
            from pathlib import Path as _Path
            _tessdata = _Path(settings.tessdata_dir).resolve()
            if _tessdata.is_dir() and any(_tessdata.glob("*.traineddata")):
                os.environ["TESSDATA_PREFIX"] = str(_tessdata)
                logger.info("OCR : tessdata local → %s", _tessdata)
        except Exception as _e:
            logger.debug("tessdata local non appliqué : %s", _e)
        try:
            _installed_langs = set(pytesseract.get_languages(config=""))
        except Exception as e:  # binaire injoignable, droits, etc.
            logger.debug("Liste des langues Tesseract indisponible : %s", e)
            _installed_langs = set()
        _wanted = [lang for lang in ("fra", "eng") if lang in _installed_langs]
        if _wanted:
            _OCR_LANGS = "+".join(_wanted)
        if _installed_langs and "fra" not in _installed_langs:
            logger.warning(
                "Pack de langue Tesseract 'fra' absent (langues présentes : %s) — "
                "OCR en anglais uniquement, qualité dégradée sur les PDF scannés en "
                "français. Installez fra.traineddata dans le dossier tessdata "
                "(https://github.com/tesseract-ocr/tessdata).",
                ", ".join(sorted(_installed_langs)) or "aucune",
            )
except ImportError:
    pass


# Mesuré en réel : cas normal < 5s ; cas pathologique (97 pages, tableaux denses)
# observé à 781s pour pymupdf4llm seul. Passé ce délai, on n'attend plus ce chemin.
#
# Volontairement PAS de seuil de pages en complément : un seul document pathologique
# mesuré (97 pages, tableaux denses) ne suffit pas à établir que "beaucoup de pages"
# est LA cause — ça pourrait tout aussi bien être la densité des tableaux, indépendante
# du nombre de pages. Un seuil de pages sacrifierait la qualité (Markdown structuré,
# tableaux propres) de gros documents par ailleurs simples et rapides à traiter, alors
# que ce sont souvent les documents les plus susceptibles de contenir les tableaux
# (bordereaux de prix, grilles d'exigences) où pymupdf4llm apporte le plus de valeur.
# Le timeout ci-dessus suffit : borné par le comportement réel observé, pas par une
# hypothèse non vérifiée sur sa cause.
_PYMUPDF4LLM_TIMEOUT_S = 25

# Chemin en constante de MODULE (pas recalculé inline) pour rester monkeypatchable
# dans les tests — ex. pointer vers un faux worker lent pour vérifier le kill au
# timeout sans dépendre d'un vrai document pathologique de plusieurs minutes.
_WORKER_SCRIPT = Path(__file__).resolve().parent / "_pymupdf4llm_worker.py"

# Extraction PAGE PAR PAGE (pdfplumber + PyMuPDF + détection d'image) en PARALLÈLE :
# mesuré en prod, cette étape à elle seule prenait ~130s sur un AO de 97 pages —
# AVANT même le premier appel LLM. Les pages sont indépendantes et ce travail est
# CPU-bound en pur Python (parsing pdfminer) : le GIL empêcherait tout gain par
# threads, d'où des PROCESSUS. Plafonné à cpu_count()-1 : sur le VPS de prod partagé
# (4 cœurs, 6 apps clientes), on laisse toujours au moins un cœur aux autres — un
# court pic de charge sur les cœurs restants pour gagner ~100s de latence utilisateur
# est un compromis délibéré, documenté ici comme lors du choix du sous-processus
# tuable pour pymupdf4llm plus haut. En-deçà de _PARALLEL_EXTRACT_MIN_PAGES, le coût
# de démarrage d'un pool de processus ne serait pas rentabilisé : on reste séquentiel.
_PARALLEL_EXTRACT_MIN_PAGES = 12
_PARALLEL_EXTRACT_MAX_WORKERS = max(1, (os.cpu_count() or 4) - 1)


class PDFAdapter(DocumentParser):
    """
    Extraction de texte PDF avec cascade :
    0. pymupdf4llm — Markdown structuré (titres, tableaux, listes) ; repli si fidélité < seuil
       ou si > _PYMUPDF4LLM_TIMEOUT_S (voir parse()). Sauté d'entrée sur un scan détecté
       (voir triage, `_looks_like_scan`).
    0bis. Sur un scan détecté : VISION LLM d'abord si disponible (`_vision`, injecté par le
       container via `set_vision_extractor`) — appels réseau PARALLÈLES, pas de contention
       CPU avec les autres apps du VPS partagé, contrairement à l'OCR local séquentiel.
    1. pdfplumber  — PDFs structurés standard (texte plat)
    2. PyMuPDF     — PDFs complexes / encodage non-standard
    3. OCR (PyMuPDF + pytesseract) — repli si la vision est indisponible/vide, ou sur les
       PDFs mixtes (texte + quelques pages-images maigres, non couverts par le triage scan).
    """

    def __init__(self, vision_extractor=None):
        # vision_extractor : DocumentVisionExtractor (ou compatible, exposant `available`
        # et `transcribe_pdf_bytes`) — None si la vision est désactivée ou pas encore
        # injectée. Optionnel : construit après le parser dans container.py (le vision
        # extractor a lui-même besoin de l'adaptateur LLM Claude), d'où `set_vision_extractor`
        # pour l'injection tardive plutôt qu'un paramètre de constructeur obligatoire.
        self._vision = vision_extractor

    def set_vision_extractor(self, vision_extractor) -> None:
        """Injection tardive du vision extractor (cf. container.py — construit après le
        parser). Pas d'effet si appelé avec None (vision restera indisponible)."""
        self._vision = vision_extractor

    async def parse(self, file_path: str) -> str:
        """Point d'entrée async — délègue tout le travail CPU/IO-bound (pymupdf4llm,
        pdfplumber, PyMuPDF, OCR Tesseract page par page) hors de la boucle
        d'événements uvicorn, pour que le serveur reste réactif au reste du trafic
        (login, dashboard, autres utilisateurs) pendant l'extraction.

        GARDE-FOU DE TEMPS sur pymupdf4llm, en SOUS-PROCESSUS (pas un thread) :
        mesuré en réel sur un AO de 97 pages à tableaux denses, `pymupdf4llm.
        to_markdown()` seul a mis 781s (13 min) — un cas pathologique, pas la norme,
        mais qui doit rester BORNÉ. Un thread orphelin ne peut pas être tué et
        continuerait de consommer un cœur CPU entier jusqu'à sa fin naturelle ; sur
        un VPS partagé entre plusieurs projets (4 cœurs, 6 apps), ce cœur monopolisé
        pendant de longues minutes dégraderait les AUTRES apps de la machine, pas
        seulement la nôtre. Le sous-processus, lui, est vraiment `kill()`é au
        timeout — le CPU est libéré immédiatement, pas juste la boucle d'événements.

        TRIAGE en amont (routeur, pas cascade « tout essayer ») : un scan (couche
        texte quasi absente) fait toujours échouer `pymupdf4llm` (il ne rend que des
        tirets vides sur une page-image, confirmé en prod) — le lancer quand même
        coûte le démarrage du sous-processus + son traitement pour un résultat qu'on
        sait déjà inexploitable. Un pré-check PyMuPDF seul (rapide, pas de pdfplumber)
        permet de sauter directement au pipeline texte/OCR sur ces documents. NE
        COUVRE PAS le cas inverse (AO dense en tableaux qui fait dégénérer
        pymupdf4llm, ex. 781s) : aucune heuristique fiable et rapide identifiée ce
        soir pour prédire CE cas sans risquer de dégrader la qualité sur de gros AO
        par ailleurs simples — le garde-fou de timeout ci-dessous reste la seule
        protection pour ce cas-là."""
        if _PYMUPDF4LLM_AVAILABLE and _FITZ_AVAILABLE:
            looks_scanned = await asyncio.to_thread(self._looks_like_scan, file_path)
            if looks_scanned:
                logger.info(
                    "PDF détecté comme scan (couche texte quasi absente) — "
                    "pymupdf4llm sauté : %s", file_path,
                )
                if self._vision is not None and getattr(self._vision, "available", False):
                    vision_text = await self._try_vision_ocr(file_path)
                    if vision_text.strip():
                        logger.info(
                            "Scan transcrit via vision LLM (%d car., appels réseau "
                            "parallèles — aucune contention CPU) : %s",
                            len(vision_text), file_path,
                        )
                        return vision_text
                    logger.info(
                        "Vision LLM indisponible/vide — repli sur l'OCR Tesseract "
                        "séquentiel : %s", file_path,
                    )
                return await asyncio.to_thread(self._parse_fallback_sync, file_path)
        if _PYMUPDF4LLM_AVAILABLE:
            markdown = await self._run_pymupdf4llm_subprocess(file_path)
            if markdown and _alnum_count(markdown) >= _FIDELITY_MIN_BASELINE:
                # On n'accepte le raccourci Markdown que s'il porte VRAIMENT du texte. Sur
                # un PDF scanné (pages-images), pymupdf4llm rend chaque page en règle
                # horizontale « ----- » sans contenu alphanumérique. _is_faithful() jugeait
                # alors ces tirets « fidèles » à une couche texte de référence elle aussi
                # vide (baseline < seuil → True) et les retournait, COURT-CIRCUITANT l'OCR
                # → le LLM ne recevait que des tirets. D'où l'exigence d'un minimum de
                # contenu réel avant de shortcut ; sinon repli sur le pipeline texte/OCR.
                baseline = await asyncio.to_thread(self._plain_text_baseline, file_path)
                if _is_faithful(markdown, baseline):
                    logger.info(
                        "PDF → Markdown via pymupdf4llm (%d caractères) : %s",
                        len(markdown), file_path,
                    )
                    return markdown
                logger.warning(
                    "PDF → Markdown rejeté (fidélité %d/%d car. alphanum. < %.0f %%) — "
                    "repli sur le pipeline texte/OCR : %s",
                    _alnum_count(markdown), _alnum_count(baseline),
                    _FIDELITY_MIN_RATIO * 100, file_path,
                )
            elif markdown:
                logger.info(
                    "PDF → Markdown ignoré (contenu réel insuffisant : %d car. alphanum. < %d) — "
                    "probable PDF scanné, repli sur le pipeline texte/OCR : %s",
                    _alnum_count(markdown), _FIDELITY_MIN_BASELINE, file_path,
                )
        return await asyncio.to_thread(self._parse_fallback_sync, file_path)

    async def _run_pymupdf4llm_subprocess(self, file_path: str) -> str:
        """Lance `_pymupdf4llm_worker.py` dans un sous-processus séparé, avec un
        timeout qui le TUE réellement (SIGKILL) s'il dépasse `_PYMUPDF4LLM_TIMEOUT_S`
        — contrairement à un thread, aucun travail CPU orphelin ne survit à
        l'abandon. "" si indisponible/tué/en échec : ne lève jamais, le pipeline
        texte/OCR sait toujours prendre le relais."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            output_path = tmp.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(_WORKER_SCRIPT), file_path, output_path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=_PYMUPDF4LLM_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning(
                    "pymupdf4llm > %ds sur %s — sous-processus TUÉ (CPU libéré "
                    "immédiatement, aucun travail orphelin), repli sur le pipeline "
                    "texte/OCR page par page.",
                    _PYMUPDF4LLM_TIMEOUT_S, file_path,
                )
                proc.kill()
                await proc.wait()
                return ""
            if proc.returncode != 0:
                logger.debug("pymupdf4llm (sous-processus) échoué sur %s", file_path)
                return ""
            return await asyncio.to_thread(
                lambda: Path(output_path).read_text(encoding="utf-8").strip()
            )
        finally:
            Path(output_path).unlink(missing_ok=True)

    def _parse_fallback_sync(self, file_path: str) -> str:
        # Décision OCR PAGE PAR PAGE (et non sur la moyenne du document) : un CV peut
        # avoir des pages texte ET une page de certifications/diplômes en image. Une
        # moyenne globale « ok » sauterait l'OCR et perdrait cette page-image noyée dans
        # un document par ailleurs textuel. On OCR-ise donc uniquement les pages maigres.
        n_pages = self._page_count(file_path)
        if n_pages == 0:
            logger.warning("Aucune page lisible dans %s", file_path)
            return ""

        per_page = self._extract_pages(file_path, n_pages)

        # Par page : on garde la couche texte la plus riche (pdfplumber vs PyMuPDF).
        pages: list[str] = []
        thin_pages: list[int] = []
        for i in range(n_pages):
            info = per_page.get(i) or {"plumber": "", "mupdf": "", "image_heavy": False}
            p, m = info["plumber"], info["mupdf"]
            best = m if len(m) > len(p) else p
            pages.append(best)
            n_chars = len(best.strip())
            # Maigre si : (a) presque pas de texte, ou (b) image significative + texte modéré
            # (cas « Certifications » : un titre/légende noie le seuil mais le contenu est en image).
            if n_chars < settings.ocr_min_chars_per_page or (
                info["image_heavy"] and n_chars < settings.ocr_image_page_text_max
            ):
                thin_pages.append(i)

        # OCR ciblé : seulement les pages à couche texte maigre (scans, certifs en image).
        # Réactivé : le diagnostic réel (désactivation temporaire + chronométrage isolé)
        # a confirmé que l'OCR n'était PAS le goulot de lenteur — voir _PYMUPDF4LLM_TIMEOUT_S
        # ci-dessus pour le vrai coupable (pymupdf4llm sur les documents à tableaux denses).
        if thin_pages and _FITZ_AVAILABLE and _TESSERACT_AVAILABLE:
            logger.info(
                "OCR ciblé sur %d/%d page(s) maigre(s) de %s : pages %s",
                len(thin_pages), n_pages, file_path, thin_pages,
            )
            ocr_by_page = self._ocr_pages(file_path, thin_pages)
            for i, otext in ocr_by_page.items():
                if len(otext) > len(pages[i]):
                    logger.info("Page %d de %s récupérée par OCR (%d chars)", i, file_path, len(otext))
                    pages[i] = otext
        elif thin_pages and not (_FITZ_AVAILABLE and _TESSERACT_AVAILABLE):
            logger.warning(
                "%d page(s) maigre(s) dans %s mais OCR indisponible (fitz=%s, tesseract=%s) "
                "— contenu en image non lu.",
                len(thin_pages), file_path, _FITZ_AVAILABLE, _TESSERACT_AVAILABLE,
            )

        result = "\n\n".join(p for p in pages if p.strip())
        if not result:
            logger.warning("Aucun texte extrait de %s", file_path)
        return result

    @staticmethod
    def _extract_pages(file_path: str, n_pages: int) -> dict[int, dict]:
        """Extrait pdfplumber + PyMuPDF + détection d'image significative pour
        TOUTES les pages — en parallèle (processus bornés, cf. `_PARALLEL_EXTRACT_
        MAX_WORKERS`) au-delà de `_PARALLEL_EXTRACT_MIN_PAGES`, sinon séquentiel dans
        le processus courant (le démarrage d'un pool ne se rentabilise pas sur un
        petit document). Renvoie {index_page: {"plumber", "mupdf", "image_heavy"}}."""
        if n_pages < _PARALLEL_EXTRACT_MIN_PAGES:
            return _extract_page_range(file_path, list(range(n_pages)))

        n_workers = min(_PARALLEL_EXTRACT_MAX_WORKERS, n_pages)
        # Répartition round-robin (pas par bloc contigu) : équilibre mieux la charge si
        # la densité (tableaux, images) n'est pas uniforme sur le document.
        chunks = [list(range(start, n_pages, n_workers)) for start in range(n_workers)]
        result: dict[int, dict] = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = [executor.submit(_extract_page_range, file_path, c) for c in chunks if c]
            for future in concurrent.futures.as_completed(futures):
                result.update(future.result())
        return result

    @staticmethod
    def _page_count(file_path: str) -> int:
        """Nombre de pages (best-effort). Sert au seuil chars/page. 0 si indéterminable."""
        if _FITZ_AVAILABLE:
            try:
                import fitz
                with fitz.open(file_path) as doc:
                    return len(doc)
            except Exception:
                pass
        try:
            with pdfplumber.open(file_path) as pdf:
                return len(pdf.pages)
        except Exception:
            return 0

    @staticmethod
    def _text_layer_ok(text: str, n_pages: int) -> bool:
        """La couche texte est-elle assez fournie, ou faut-il tenter l'OCR ?

        Heuristique : si on a moins de `ocr_min_chars_per_page` caractères par page en
        moyenne, le PDF est probablement scanné avec une couche texte résiduelle (tampons,
        en-têtes) → l'OCR donnera mieux. n_pages inconnu (0) → on fait confiance au texte.
        """
        if n_pages <= 0:
            return bool(text.strip())
        return (len(text) / n_pages) >= settings.ocr_min_chars_per_page

    # ── Extracteurs ────────────────────────────────────────────────────────────
    # (la conversion pymupdf4llm elle-même vit dans _pymupdf4llm_worker.py,
    # exécutée en sous-processus tuable — voir _run_pymupdf4llm_subprocess ci-dessus)

    def _looks_like_scan(self, file_path: str) -> bool:
        """Pré-check RAPIDE (PyMuPDF seul, pas de pdfplumber ni pymupdf4llm) : ce PDF
        a-t-il une couche texte quasi absente ? Même seuil (`_FIDELITY_MIN_BASELINE`)
        que celui déjà utilisé pour juger la sortie de pymupdf4llm insuffisante —
        cohérent, puisque les deux mesurent le même signal (densité alphanumérique
        réelle du texte natif du PDF)."""
        text = self._try_pymupdf(file_path)
        return _alnum_count(text) < _FIDELITY_MIN_BASELINE

    async def _try_vision_ocr(self, file_path: str) -> str:
        """Transcrit un scan via le vision LLM injecté (`self._vision`) — best-effort :
        renvoie '' (jamais d'exception) sur tout échec, le caller retombe alors sur
        Tesseract. Lit le fichier en octets (l'API vision travaille sur des octets, pas
        un chemin) via un thread pour ne pas bloquer la boucle d'événements."""
        try:
            file_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
            return await self._vision.transcribe_pdf_bytes(
                file_bytes, max_pages=settings.ocr_max_pages)
        except Exception as exc:
            logger.warning("Vision OCR échouée sur %s (%s) — repli Tesseract.", file_path, exc)
            return ""

    def _plain_text_baseline(self, file_path: str) -> str:
        """Texte plat de référence pour juger la fidélité du Markdown (PyMuPDF puis pdfplumber)."""
        if _FITZ_AVAILABLE:
            text = self._try_pymupdf(file_path)
            if text:
                return text
        return self._try_pdfplumber(file_path)

    @staticmethod
    def _image_heavy_pages(file_path: str) -> set[int]:
        """Indices des pages contenant ≥ 1 image couvrant une fraction significative de la page
        (settings.ocr_image_area_ratio). Sert à repérer les certifs/diplômes scannés posés sur
        une page par ailleurs peu textuelle. Best-effort : toute erreur → page non signalée."""
        heavy: set[int] = set()
        try:
            import fitz
            with fitz.open(file_path) as doc:
                for i, page in enumerate(doc):
                    page_area = abs(page.rect.width * page.rect.height)
                    if page_area <= 0:
                        continue
                    try:
                        infos = page.get_image_info()
                    except Exception:
                        continue
                    for info in infos:
                        bbox = info.get("bbox")
                        if not bbox:
                            continue
                        w, h = (bbox[2] - bbox[0]), (bbox[3] - bbox[1])
                        if (abs(w * h) / page_area) >= settings.ocr_image_area_ratio:
                            heavy.add(i)
                            break
        except Exception as e:
            logger.debug("Détection d'images échouée sur %s : %s", file_path, e)
        return heavy

    def _pdfplumber_pages(self, file_path: str) -> list[str]:
        """Texte par page via pdfplumber (tableaux rendus en Markdown inclus)."""
        try:
            with pdfplumber.open(file_path) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=3, y_tolerance=3)
                    if not text:
                        words = page.extract_words()
                        if words:
                            text = " ".join(w["text"] for w in words)
                    parts = []
                    if text and text.strip():
                        parts.append(text.strip())
                    # Les grilles de notation, profils et annexes des AO sont en tableaux :
                    # extract_text() les aplatit (colonnes/lignes mélangées). On ré-ajoute
                    # chaque tableau rendu en Markdown pour préserver la structure ligne/colonne.
                    tables_md = self._render_tables(page)
                    if tables_md:
                        parts.append(tables_md)
                    pages.append("\n\n".join(parts))
            return pages
        except Exception as e:
            logger.debug("pdfplumber échoué sur %s : %s", file_path, e)
            return []

    def _try_pdfplumber(self, file_path: str) -> str:
        return "\n\n".join(p for p in self._pdfplumber_pages(file_path) if p.strip())

    @staticmethod
    def _render_tables(page) -> str:
        """Rend les tableaux d'une page en Markdown (| col | col |) pour conserver leur structure.

        Tolérant : toute erreur d'extraction de tableau est ignorée (le texte linéaire reste
        la source principale). Les lignes/cellules vides sont normalisées en chaînes vides.
        """
        try:
            tables = page.extract_tables()
        except Exception:
            return ""
        if not tables:
            return ""
        blocks = []
        for idx, table in enumerate(tables, 1):
            rows = []
            for row in table or []:
                cells = [" ".join((c or "").split()) for c in row]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                blocks.append(f"[TABLEAU {idx}]\n" + "\n".join(rows))
        return "\n\n".join(blocks)

    def _pymupdf_pages(self, file_path: str) -> list[str]:
        """Texte par page via PyMuPDF."""
        try:
            import fitz
            pages = []
            with fitz.open(file_path) as doc:
                for page in doc:
                    text = page.get_text("text")
                    pages.append(text.strip() if text else "")
            return pages
        except Exception as e:
            logger.debug("PyMuPDF échoué sur %s : %s", file_path, e)
            return []

    def _try_pymupdf(self, file_path: str) -> str:
        return "\n\n".join(p for p in self._pymupdf_pages(file_path) if p.strip())

    def _ocr_pages(self, file_path: str, page_indices: list[int]) -> dict[int, str]:
        """OCR ciblé : rend chaque page demandée en image (200 DPI) puis Tesseract (fra+eng).
        Retourne {index_page: texte}. Cappé à settings.ocr_max_pages pages OCR-isées.
        Utilise les langues réellement installées (_OCR_LANGS, idéalement fra+eng)."""
        try:
            import fitz
            import pytesseract
            from PIL import Image

            out: dict[int, str] = {}
            with fitz.open(file_path) as doc:
                n = len(doc)
                wanted = [i for i in page_indices if 0 <= i < n]
                cap = settings.ocr_max_pages
                if len(wanted) > cap:
                    logger.warning(
                        "OCR TRONQUÉ : %d pages à OCR-iser sur %s, cap=%d — pages %s non lues. "
                        "Relever settings.ocr_max_pages si nécessaire.",
                        len(wanted), file_path, cap, wanted[cap:],
                    )
                    wanted = wanted[:cap]
                # 200 DPI : bon compromis vitesse/qualité (était 300 DPI → trop lent)
                mat = fitz.Matrix(200 / 72, 200 / 72)
                for i in wanted:
                    logger.debug("OCR page %d de %s…", i, file_path)
                    pix = doc[i].get_pixmap(matrix=mat, alpha=False)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    # Langues installées (fra+eng si dispo) ; repli eng par sécurité
                    try:
                        text = pytesseract.image_to_string(img, lang=_OCR_LANGS)
                    except pytesseract.TesseractError:
                        text = pytesseract.image_to_string(img, lang="eng")
                    if text.strip():
                        out[i] = text.strip()
            return out
        except Exception as e:
            logger.warning("OCR échoué sur %s : %s", file_path, e)
            return {}

    def _try_ocr(self, file_path: str) -> str:
        """OCR de toutes les pages (compat). Préférer _ocr_pages pour l'OCR ciblé."""
        n = self._page_count(file_path)
        if n <= 0:
            return ""
        by_page = self._ocr_pages(file_path, list(range(n)))
        return "\n\n".join(by_page[i] for i in sorted(by_page))

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")


def _extract_page_range(file_path: str, page_indices: list[int]) -> dict[int, dict]:
    """Extrait pdfplumber + PyMuPDF + détection d'image significative pour un
    sous-ensemble de pages — chaque bibliothèque ouverte UNE SEULE fois par appel
    (pas par page). Fonction MODULE-LEVEL (pas une méthode) : c'est une exigence de
    `ProcessPoolExecutor`, qui doit pouvoir « pickler » la référence pour l'envoyer
    au processus enfant — une méthode liée à une instance ne s'y prête pas.
    Exécutée soit dans le processus courant (petit document), soit dans un
    sous-processus dédié (cf. `PDFAdapter._extract_pages`)."""
    mupdf_text: dict[int, str] = {}
    image_heavy: set[int] = set()
    if _FITZ_AVAILABLE:
        import fitz
        try:
            with fitz.open(file_path) as doc:
                for i in page_indices:
                    if i >= len(doc):
                        continue
                    page = doc[i]
                    text = page.get_text("text")
                    mupdf_text[i] = text.strip() if text else ""
                    page_area = abs(page.rect.width * page.rect.height)
                    if page_area <= 0:
                        continue
                    try:
                        infos = page.get_image_info()
                    except Exception:
                        infos = []
                    for info in infos:
                        bbox = info.get("bbox")
                        if not bbox:
                            continue
                        w, h = (bbox[2] - bbox[0]), (bbox[3] - bbox[1])
                        if (abs(w * h) / page_area) >= settings.ocr_image_area_ratio:
                            image_heavy.add(i)
                            break
        except Exception as e:
            logger.debug("PyMuPDF (worker page) échoué sur %s : %s", file_path, e)

    plumber_text: dict[int, str] = {}
    try:
        with pdfplumber.open(file_path) as pdf:
            for i in page_indices:
                if i >= len(pdf.pages):
                    continue
                page = pdf.pages[i]
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if not text:
                    words = page.extract_words()
                    if words:
                        text = " ".join(w["text"] for w in words)
                parts = []
                if text and text.strip():
                    parts.append(text.strip())
                tables_md = PDFAdapter._render_tables(page)
                if tables_md:
                    parts.append(tables_md)
                plumber_text[i] = "\n\n".join(parts)
    except Exception as e:
        logger.debug("pdfplumber (worker page) échoué sur %s : %s", file_path, e)

    return {
        i: {
            "plumber": plumber_text.get(i, ""),
            "mupdf": mupdf_text.get(i, ""),
            "image_heavy": i in image_heavy,
        }
        for i in page_indices
    }
