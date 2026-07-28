"""
DocumentVisionExtractor — lit le CONTENU VISUEL des pages porteuses d'images (tous types de
documents) que ni la couche texte ni l'OCR ne restituent : schémas/diagrammes, tableaux en
image, captures, logos et badges de certification.

Déclencheur ciblé (coût borné) : pages dont les images couvrent ≥ area_ratio de la surface,
OU page de CV titrée « certifications » (badges souvent petits). Ces pages sont rendues en PNG
et envoyées en UN SEUL appel à un LLM multimodal (Claude Haiku) qui transcrit + décrit, et
liste les certifications par leur nom officiel.

Best-effort : toute panne (pas de clé API, modèle indisponible, JSON invalide, doc non-PDF)
renvoie un résultat vide sans jamais interrompre l'indexation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

_VISION_SYSTEM = (
    "Tu reçois une ou plusieurs images de pages d'un document professionnel (CV, appel d'offres, "
    "attestation, schéma technique, certificat…). Pour CHAQUE page :\n"
    "- TRANSCRIS fidèlement tout le texte lisible.\n"
    "- DÉCRIS brièvement les éléments visuels porteurs d'information : schémas/diagrammes "
    "(composants et liens), tableaux (contenu principal), captures d'écran, logos/badges de "
    "certification (donne le NOM OFFICIEL complet).\n"
    "RÈGLES STRICTES : n'invente RIEN ; si un élément est illisible ou ambigu, ignore-le ; "
    "pas de commentaire décoratif.\n"
    "Réponds UNIQUEMENT par un objet JSON, sans texte autour :\n"
    '{"contenu": "<transcription + descriptions>", "certifications": ["<nom officiel>", ...]}'
)

_EMPTY = {"contenu": "", "certifications": []}

# OCR vision d'un document ENTIER (AO scanné) — transcription verbatim en TEXTE BRUT,
# contrairement à _VISION_SYSTEM qui vise les pages-images/certifs et rend du JSON.
_OCR_SYSTEM = (
    "Tu reçois une ou plusieurs images de pages d'un document (appel d'offres, cahier des "
    "charges…). TRANSCRIS FIDÈLEMENT ET INTÉGRALEMENT tout le texte lisible, page par page, "
    "dans l'ordre. Conserve la structure : titres, numéros d'articles/sections, listes, et "
    "les TABLEAUX (rends chaque tableau ligne par ligne, cellules séparées par ' | '). "
    "N'invente RIEN, ne résume RIEN, n'ajoute aucun commentaire. Si un passage est illisible, "
    "écris [illisible]. Réponds UNIQUEMENT avec le texte transcrit, sans balises ni préambule."
)

# Pages par appel vision : borne la taille de sortie (une page dense ≈ 800-1500 tokens de
# texte ; 4 pages tiennent largement sous le plafond max_tokens ci-dessous sans troncature).
_OCR_PAGES_PER_CALL = 4
_OCR_MAX_TOKENS = 8000

# Appels vision EN PARALLÈLE (borné) plutôt que séquentiels : chaque lot est un appel
# réseau indépendant (pas de contention CPU comme Tesseract page par page — c'est
# précisément l'intérêt de la vision pour les scans). Plafonné pour rester raisonnable
# vis-à-vis des limites de débit Anthropic, pas du CPU du VPS.
_OCR_MAX_CONCURRENT_CALLS = 4


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


class DocumentVisionExtractor:
    def __init__(self, vision_llm, max_pages: int = 3, area_ratio: float = 0.15, dpi: int = 150):
        # vision_llm : objet exposant generate_with_images(system, user, images, ...).
        self._llm = vision_llm
        self._max_pages = max_pages
        self._area_ratio = area_ratio
        self._dpi = dpi

    @property
    def available(self) -> bool:
        return self._llm is not None and hasattr(self._llm, "generate_with_images")

    @staticmethod
    def _page_image_ratio(page) -> float:
        """Part de la surface de la page couverte par des images (0–1)."""
        try:
            infos = page.get_image_info()
        except Exception:
            return 0.0
        page_area = abs(page.rect.width * page.rect.height) or 1.0
        covered = 0.0
        for it in infos or []:
            bb = it.get("bbox")
            if bb and len(bb) == 4:
                covered += abs((bb[2] - bb[0]) * (bb[3] - bb[1]))
        return min(1.0, covered / page_area)

    def _candidate_pages(self, doc) -> list[int]:
        """Pages valant un appel vision : forte couverture image, OU page « certif » à logos,
        OU page-image à faible texte suivant un titre « certif »."""
        pages_text = [_normalize(p.get_text()) for p in doc]
        candidates: list[int] = []
        for i, page in enumerate(doc):
            if not page.get_images(full=True):
                continue
            here = pages_text[i]
            prev = pages_text[i - 1] if i > 0 else ""
            if self._page_image_ratio(page) >= self._area_ratio:
                candidates.append(i)
            elif "certif" in here:
                candidates.append(i)
            elif "certif" in prev and len(here.strip()) < 400:
                candidates.append(i)
        return candidates[: self._max_pages]

    async def extract(self, file_path: Path, doc_type=None) -> dict:
        """Renvoie {"contenu": str, "certifications": list[str]} ; vide si rien à analyser."""
        if not self.available:
            return dict(_EMPTY)
        path = Path(file_path)
        if path.suffix.lower() != ".pdf":
            return dict(_EMPTY)
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.debug("PyMuPDF absent — extraction vision désactivée.")
            return dict(_EMPTY)

        try:
            doc = fitz.open(str(path))
        except Exception as exc:
            logger.warning("Vision : ouverture PDF échouée (%s) : %s", path.name, exc)
            return dict(_EMPTY)
        try:
            pages = self._candidate_pages(doc)
            if not pages:
                return dict(_EMPTY)
            images: list[tuple[str, bytes]] = []
            for idx in pages:
                pix = doc[idx].get_pixmap(dpi=self._dpi)
                images.append(("image/png", pix.tobytes("png")))
        except Exception as exc:
            logger.warning("Vision : rendu des pages échoué (%s) : %s", path.name, exc)
            return dict(_EMPTY)
        finally:
            doc.close()

        user = "Voici la/les page(s) à contenu visuel de ce document. Transcris et décris fidèlement."
        try:
            raw = await self._llm.generate_with_images(
                system=_VISION_SYSTEM, user=user, images=images,
                max_tokens=4000, temperature=0.0,   # transcription multi-pages = verbeux
            )
        except Exception as exc:
            logger.warning("Vision : appel LLM échoué (%s) : %s", path.name, exc)
            return dict(_EMPTY)

        result = self._parse(raw)
        if result["contenu"] or result["certifications"]:
            logger.info(
                "Vision : %d page(s) lue(s) sur %s (%d certif, %d chars de contenu)",
                len(pages), path.name, len(result["certifications"]), len(result["contenu"]),
            )
        return result

    async def _transcribe_batch(
        self, batch: list[tuple[str, bytes]], start: int, semaphore: asyncio.Semaphore,
    ) -> str:
        """Transcrit UN lot de pages — appelé en parallèle (borné par `semaphore`) depuis
        `transcribe_pdf_bytes`. Best-effort : renvoie '' sur échec, jamais d'exception."""
        async with semaphore:
            user = (
                f"Pages {start + 1} à {start + len(batch)} du document. "
                "Transcris fidèlement et intégralement."
            )
            try:
                raw = await self._llm.generate_with_images(
                    system=_OCR_SYSTEM, user=user, images=batch,
                    max_tokens=_OCR_MAX_TOKENS, temperature=0.0,
                )
            except Exception as exc:
                logger.warning("OCR vision : lot pages %d+ échoué : %s", start + 1, exc)
                return ""
            return raw.strip() if raw and raw.strip() else ""

    async def transcribe_pdf_bytes(self, file_bytes: bytes, max_pages: int | None = None) -> str:
        """OCR VISION d'un PDF entier (AO scanné) → texte brut transcrit, best-effort.

        Rend chaque page en PNG (jusqu'à `max_pages`) et la transcrit par lots de
        `_OCR_PAGES_PER_CALL`, LOTS EN PARALLÈLE (borné à `_OCR_MAX_CONCURRENT_CALLS` —
        appels réseau indépendants, pas de contention CPU comme un OCR local séquentiel).
        Renvoie '' si la vision est indisponible, si PyMuPDF est absent, ou si le PDF est
        illisible — jamais d'exception. Ouvre le PDF depuis les octets (pas de fichier
        temporaire)."""
        if not self.available:
            return ""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.debug("PyMuPDF absent — OCR vision désactivé.")
            return ""
        cap = max_pages if max_pages and max_pages > 0 else self._max_pages
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            logger.warning("OCR vision : ouverture PDF échouée : %s", exc)
            return ""
        try:
            images: list[tuple[str, bytes]] = []
            for i, page in enumerate(doc):
                if i >= cap:
                    logger.warning(
                        "OCR vision TRONQUÉ : PDF de %d pages, cap=%d — pages restantes non lues "
                        "(relever settings.ocr_max_pages).", doc.page_count, cap,
                    )
                    break
                pix = page.get_pixmap(dpi=self._dpi)
                images.append(("image/png", pix.tobytes("png")))
        except Exception as exc:
            logger.warning("OCR vision : rendu des pages échoué : %s", exc)
            return ""
        finally:
            doc.close()
        if not images:
            return ""

        semaphore = asyncio.Semaphore(_OCR_MAX_CONCURRENT_CALLS)
        batches = [
            (images[start : start + _OCR_PAGES_PER_CALL], start)
            for start in range(0, len(images), _OCR_PAGES_PER_CALL)
        ]
        # gather préserve l'ORDRE des résultats (= ordre des pages), même si les lots
        # se terminent dans un ordre différent — la reconstitution reste correcte.
        results = await asyncio.gather(
            *(self._transcribe_batch(batch, start, semaphore) for batch, start in batches)
        )
        return "\n\n".join(r for r in results if r)

    @staticmethod
    def _dedup(names: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in names:
            name = str(it).strip()
            key = _normalize(name)
            if name and key not in seen:
                seen.add(key)
                out.append(name)
        return out

    @classmethod
    def _parse(cls, raw: str) -> dict:
        """Tolère le fence ```json ... ``` ET un JSON TRONQUÉ (réponse coupée au plafond de
        tokens) : on tente d'abord json.loads, puis une récupération best-effort par regex."""
        if not raw:
            return dict(_EMPTY)
        # Essai 1 : JSON complet (la regex { … } ignore un éventuel fence markdown autour).
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    certs = data.get("certifications")
                    return {
                        "contenu": str(data.get("contenu") or "").strip(),
                        "certifications": cls._dedup(certs if isinstance(certs, list) else []),
                    }
            except (ValueError, TypeError):
                pass  # JSON tronqué/malformé → récupération ci-dessous
        # Essai 2 : récupérer au moins "contenu" (chaîne éventuellement non fermée) + certifs.
        contenu = ""
        cm = re.search(r'"contenu"\s*:\s*"(.*)', raw, re.DOTALL)
        if cm:
            s = re.split(r'",\s*"certifications"', cm.group(1))[0].rstrip().rstrip('"')
            contenu = s.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t").strip()
        certs: list[str] = []
        block = re.search(r'"certifications"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
        if block:
            certs = cls._dedup(re.findall(r'"([^"]+)"', block.group(1)))
        return {"contenu": contenu, "certifications": certs}
