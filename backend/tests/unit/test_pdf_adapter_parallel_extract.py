"""PDFAdapter — extraction page par page (pdfplumber + PyMuPDF) en PARALLÈLE
au-delà d'un certain nombre de pages. Bug de lenteur réel observé en prod : cette
étape à elle seule prenait ~130s sur un AO de 97 pages, AVANT même le premier appel
LLM — les pages sont indépendantes, ce travail CPU-bound (parsing pdfminer pur
Python) se prête à des processus. Ces tests vérifient que le résultat est identique
qu'on passe par le chemin séquentiel (petit document) ou parallèle (gros document),
et que le seuil de bascule fonctionne."""
import asyncio

import fitz
import pytest

import adapters.parser.pdf_adapter as pdf_adapter_module
from adapters.parser.pdf_adapter import PDFAdapter, _extract_page_range


def _make_text_pdf(path, n_pages: int) -> None:
    """Construit un vrai PDF de `n_pages` pages, chacune avec un texte distinct et
    identifiable (page N) — permet de vérifier après coup que chaque page a été lue
    correctement et dans le bon ordre, quel que soit le chemin d'extraction."""
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Contenu de la page numero {i}")
    doc.save(str(path))
    doc.close()


def test_extract_page_range_lit_le_texte_de_chaque_page(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    _make_text_pdf(pdf_path, 3)

    result = _extract_page_range(str(pdf_path), [0, 1, 2])

    assert set(result.keys()) == {0, 1, 2}
    for i in range(3):
        assert f"page numero {i}" in result[i]["mupdf"]


def test_extract_pages_sous_le_seuil_reste_sequentiel(tmp_path, monkeypatch):
    pdf_path = tmp_path / "petit.pdf"
    _make_text_pdf(pdf_path, 3)
    calls = []
    real = pdf_adapter_module._extract_page_range

    def _spy(file_path, page_indices):
        calls.append(list(page_indices))
        return real(file_path, page_indices)

    monkeypatch.setattr(pdf_adapter_module, "_extract_page_range", _spy)

    result = PDFAdapter._extract_pages(str(pdf_path), 3)

    assert len(calls) == 1  # un seul appel direct (pas de découpage en workers)
    assert calls[0] == [0, 1, 2]
    assert "page numero 0" in result[0]["mupdf"]
    assert "page numero 2" in result[2]["mupdf"]


def test_extract_pages_parallele_donne_le_meme_resultat_que_sequentiel(tmp_path, monkeypatch):
    # Seuil abaissé pour forcer le chemin parallèle sans dépendre d'un vrai document
    # de 12+ pages dans le test.
    monkeypatch.setattr(pdf_adapter_module, "_PARALLEL_EXTRACT_MIN_PAGES", 2)
    monkeypatch.setattr(pdf_adapter_module, "_PARALLEL_EXTRACT_MAX_WORKERS", 3)
    pdf_path = tmp_path / "moyen.pdf"
    n_pages = 7
    _make_text_pdf(pdf_path, n_pages)

    parallel_result = PDFAdapter._extract_pages(str(pdf_path), n_pages)
    sequential_result = _extract_page_range(str(pdf_path), list(range(n_pages)))

    assert set(parallel_result.keys()) == set(range(n_pages))
    for i in range(n_pages):
        assert parallel_result[i]["mupdf"] == sequential_result[i]["mupdf"]
        assert parallel_result[i]["plumber"] == sequential_result[i]["plumber"]


def test_parse_fallback_sync_conserve_ordre_et_contenu_des_pages(tmp_path, monkeypatch):
    """Bout-en-bout : le texte final assemblé par _parse_fallback_sync doit rester
    dans l'ordre des pages et contenir le texte de chacune, que l'extraction sous-jacente
    ait tourné en séquentiel ou en parallèle."""
    monkeypatch.setattr(pdf_adapter_module, "_PARALLEL_EXTRACT_MIN_PAGES", 2)
    pdf_path = tmp_path / "ordre.pdf"
    n_pages = 5
    _make_text_pdf(pdf_path, n_pages)

    adapter = PDFAdapter()
    result = adapter._parse_fallback_sync(str(pdf_path))

    positions = [result.find(f"page numero {i}") for i in range(n_pages)]
    assert all(p != -1 for p in positions)  # chaque page présente
    assert positions == sorted(positions)  # dans l'ordre d'origine
