"""DocumentVisionExtractor.transcribe_pdf_bytes — lots de pages transcrits EN
PARALLÈLE (borné) plutôt que séquentiellement. Contrairement à l'OCR Tesseract local
(CPU-bound, séquentiel par nécessité sur un VPS partagé), les appels vision sont des
requêtes réseau indépendantes : la concurrence ne coûte rien au CPU des autres apps.
Ces tests vérifient l'ordre de reconstitution, la borne de concurrence, et la
tolérance à l'échec partiel d'un lot (best-effort, jamais d'exception remontée)."""
import asyncio

import fitz

import core.services.document_vision_extractor as dve_module
from core.services.document_vision_extractor import DocumentVisionExtractor


def _make_pdf_bytes(n_pages: int) -> bytes:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i}")
    data = doc.tobytes()
    doc.close()
    return data


class _FakeVisionLLM:
    """Simule `generate_with_images` : renvoie un texte dérivé du prompt `user` (contient
    la plage de pages) pour vérifier l'ORDRE de reconstitution après coup, et piste le
    nombre d'appels EN VOL simultanément pour vérifier la borne de concurrence."""

    def __init__(self, fail_on_start=None, delay: float = 0.0):
        self.fail_on_start = fail_on_start or set()
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0

    async def generate_with_images(self, system, user, images, max_tokens=8000, temperature=0.0):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            for start in self.fail_on_start:
                if user.startswith(f"Pages {start + 1} "):
                    raise RuntimeError("échec simulé")
            return f"[TEXTE:{user}]"
        finally:
            self.in_flight -= 1


def test_transcribe_pdf_bytes_preserve_ordre_des_pages(monkeypatch):
    monkeypatch.setattr(dve_module, "_OCR_PAGES_PER_CALL", 2)
    llm = _FakeVisionLLM()
    extractor = DocumentVisionExtractor(vision_llm=llm)
    pdf_bytes = _make_pdf_bytes(6)  # 3 lots de 2 pages

    result = asyncio.run(extractor.transcribe_pdf_bytes(pdf_bytes, max_pages=6))

    parts = result.split("\n\n")
    assert len(parts) == 3
    assert "Pages 1 à 2" in parts[0]
    assert "Pages 3 à 4" in parts[1]
    assert "Pages 5 à 6" in parts[2]


def test_transcribe_pdf_bytes_limite_la_concurrence(monkeypatch):
    monkeypatch.setattr(dve_module, "_OCR_PAGES_PER_CALL", 1)
    monkeypatch.setattr(dve_module, "_OCR_MAX_CONCURRENT_CALLS", 2)
    llm = _FakeVisionLLM(delay=0.05)
    extractor = DocumentVisionExtractor(vision_llm=llm)
    pdf_bytes = _make_pdf_bytes(6)  # 6 lots de 1 page

    asyncio.run(extractor.transcribe_pdf_bytes(pdf_bytes, max_pages=6))

    assert llm.max_in_flight <= 2


def test_transcribe_pdf_bytes_tolere_echec_partiel(monkeypatch):
    monkeypatch.setattr(dve_module, "_OCR_PAGES_PER_CALL", 1)
    llm = _FakeVisionLLM(fail_on_start={1})  # le lot "page 2" (start=1) échoue
    extractor = DocumentVisionExtractor(vision_llm=llm)
    pdf_bytes = _make_pdf_bytes(3)

    result = asyncio.run(extractor.transcribe_pdf_bytes(pdf_bytes, max_pages=3))

    assert "Pages 1 à 1" in result
    assert "Pages 3 à 3" in result
    assert "Pages 2 à 2" not in result  # lot en échec absent, pas d'exception remontée


def test_transcribe_pdf_bytes_vide_si_vision_indisponible():
    class _NoVision:
        pass  # pas de generate_with_images → available=False

    extractor = DocumentVisionExtractor(vision_llm=_NoVision())
    pdf_bytes = _make_pdf_bytes(2)

    result = asyncio.run(extractor.transcribe_pdf_bytes(pdf_bytes))

    assert result == ""
