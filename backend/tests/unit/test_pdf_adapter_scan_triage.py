"""PDFAdapter — triage en amont (routeur) : un scan (couche texte quasi absente)
saute `pymupdf4llm` entièrement au lieu de le laisser tourner pour un résultat
qu'on sait déjà inexploitable (confirmé en prod : pymupdf4llm ne rend que des
tirets vides sur une page-image). Ne couvre PAS le cas dense-tableaux (aucune
heuristique fiable identifiée pour prédire ce cas sans risquer la qualité)."""
import asyncio

import fitz

from adapters.parser.pdf_adapter import PDFAdapter


def _make_blank_pdf(path, n_pages: int = 3) -> None:
    """PDF sans AUCUN texte — simule un scan pur (couche texte totalement absente)."""
    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def _make_text_pdf(path, n_pages: int = 3) -> None:
    """PDF avec du texte réel largement au-dessus du seuil de fidélité (200 car.)."""
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        for j in range(20):
            page.insert_text((72, 72 + j * 14), f"Ligne {j} de contenu réel sur la page {i}.")
    doc.save(str(path))
    doc.close()


def test_looks_like_scan_detecte_pdf_sans_texte(tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf_path)
    adapter = PDFAdapter()

    assert adapter._looks_like_scan(str(pdf_path)) is True


def test_looks_like_scan_detecte_pdf_avec_texte_normal(tmp_path):
    pdf_path = tmp_path / "normal.pdf"
    _make_text_pdf(pdf_path)
    adapter = PDFAdapter()

    assert adapter._looks_like_scan(str(pdf_path)) is False


def test_parse_saute_pymupdf4llm_sur_scan(tmp_path, monkeypatch):
    import adapters.parser.pdf_adapter as m

    pdf_path = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf_path)
    adapter = PDFAdapter()

    calls: list[str] = []

    async def _fake_pymupdf4llm_subprocess(self, file_path):
        calls.append("pymupdf4llm")
        return "ne devrait jamais être appelé"

    def _fake_fallback(self, file_path):
        calls.append("fallback")
        return "texte de repli"

    monkeypatch.setattr(m.PDFAdapter, "_run_pymupdf4llm_subprocess", _fake_pymupdf4llm_subprocess)
    monkeypatch.setattr(m.PDFAdapter, "_parse_fallback_sync", _fake_fallback)

    result = asyncio.run(adapter.parse(str(pdf_path)))

    assert calls == ["fallback"]  # pymupdf4llm jamais invoqué
    assert result == "texte de repli"


def test_parse_tente_pymupdf4llm_sur_texte_normal(tmp_path, monkeypatch):
    import adapters.parser.pdf_adapter as m

    pdf_path = tmp_path / "normal.pdf"
    _make_text_pdf(pdf_path)
    adapter = PDFAdapter()

    calls: list[str] = []

    async def _fake_pymupdf4llm_subprocess(self, file_path):
        calls.append("pymupdf4llm")
        return ""  # simule un échec — on vérifie juste que l'appel a bien lieu

    def _fake_fallback(self, file_path):
        calls.append("fallback")
        return "texte de repli"

    monkeypatch.setattr(m.PDFAdapter, "_run_pymupdf4llm_subprocess", _fake_pymupdf4llm_subprocess)
    monkeypatch.setattr(m.PDFAdapter, "_parse_fallback_sync", _fake_fallback)

    asyncio.run(adapter.parse(str(pdf_path)))

    assert calls[0] == "pymupdf4llm"  # comportement inchangé : toujours tenté sur un doc normal


def test_parse_utilise_vision_en_premier_sur_scan_si_disponible(tmp_path, monkeypatch):
    """Sur un scan, si un vision extractor DISPONIBLE est injecté, il doit être tenté
    AVANT Tesseract — et si son résultat est non vide, Tesseract ne doit jamais tourner
    (c'est le point central de la stratégie B : éviter l'OCR local séquentiel)."""
    import adapters.parser.pdf_adapter as m

    pdf_path = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf_path)
    adapter = PDFAdapter()

    class _FakeVision:
        available = True

        async def transcribe_pdf_bytes(self, file_bytes, max_pages=None):
            return "texte transcrit par la vision"

    adapter.set_vision_extractor(_FakeVision())

    calls: list[str] = []

    def _fake_fallback(self, file_path):
        calls.append("fallback")
        return "texte de repli tesseract"

    monkeypatch.setattr(m.PDFAdapter, "_parse_fallback_sync", _fake_fallback)

    result = asyncio.run(adapter.parse(str(pdf_path)))

    assert result == "texte transcrit par la vision"
    assert calls == []  # Tesseract jamais appelé


def test_parse_retombe_sur_tesseract_si_vision_vide(tmp_path, monkeypatch):
    import adapters.parser.pdf_adapter as m

    pdf_path = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf_path)
    adapter = PDFAdapter()

    class _EmptyVision:
        available = True

        async def transcribe_pdf_bytes(self, file_bytes, max_pages=None):
            return ""

    adapter.set_vision_extractor(_EmptyVision())

    def _fake_fallback(self, file_path):
        return "texte de repli tesseract"

    monkeypatch.setattr(m.PDFAdapter, "_parse_fallback_sync", _fake_fallback)

    result = asyncio.run(adapter.parse(str(pdf_path)))

    assert result == "texte de repli tesseract"


def test_parse_retombe_sur_tesseract_si_vision_leve_exception(tmp_path, monkeypatch):
    import adapters.parser.pdf_adapter as m

    pdf_path = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf_path)
    adapter = PDFAdapter()

    class _BrokenVision:
        available = True

        async def transcribe_pdf_bytes(self, file_bytes, max_pages=None):
            raise RuntimeError("API indisponible")

    adapter.set_vision_extractor(_BrokenVision())

    def _fake_fallback(self, file_path):
        return "texte de repli tesseract"

    monkeypatch.setattr(m.PDFAdapter, "_parse_fallback_sync", _fake_fallback)

    result = asyncio.run(adapter.parse(str(pdf_path)))

    assert result == "texte de repli tesseract"


def test_parse_retombe_sur_tesseract_si_vision_non_disponible(tmp_path, monkeypatch):
    """`available=False` (ex. clé API absente côté adapter concret) doit retomber sur
    Tesseract sans jamais appeler `transcribe_pdf_bytes`."""
    import adapters.parser.pdf_adapter as m

    pdf_path = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf_path)
    adapter = PDFAdapter()

    calls: list[str] = []

    class _UnavailableVision:
        available = False

        async def transcribe_pdf_bytes(self, file_bytes, max_pages=None):
            calls.append("vision")
            return "ne devrait jamais être appelé"

    adapter.set_vision_extractor(_UnavailableVision())

    def _fake_fallback(self, file_path):
        return "texte de repli tesseract"

    monkeypatch.setattr(m.PDFAdapter, "_parse_fallback_sync", _fake_fallback)

    result = asyncio.run(adapter.parse(str(pdf_path)))

    assert calls == []
    assert result == "texte de repli tesseract"
