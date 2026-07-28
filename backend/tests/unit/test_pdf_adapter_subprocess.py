"""PDFAdapter — pymupdf4llm en sous-processus TUABLE au timeout (pas un thread
orphelin). Sur un VPS partagé entre plusieurs projets, un thread abandonné
continuerait de consommer un cœur CPU entier pendant de longues minutes après
le timeout — dégradant les AUTRES apps de la machine. Le sous-processus, lui,
est réellement `kill()`é : le CPU est libéré immédiatement."""
import asyncio
import textwrap
import time
from pathlib import Path

import fitz

import adapters.parser.pdf_adapter as pdf_adapter_module
from adapters.parser.pdf_adapter import PDFAdapter


def _write_worker(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_worker.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def _make_text_pdf(path: Path) -> None:
    """PDF avec du texte réel (au-dessus du seuil de triage scan/normal) — pour les
    tests qui exercent le chemin pymupdf4llm de `parse()` et ne veulent PAS être
    déviés par le pré-check `_looks_like_scan` (cf. test_pdf_adapter_scan_triage.py)."""
    doc = fitz.open()
    page = doc.new_page()
    for i in range(20):
        page.insert_text((72, 72 + i * 14), f"Ligne {i} de contenu réel pour ce test.")
    doc.save(str(path))
    doc.close()


def test_subprocess_tue_reellement_au_timeout(tmp_path, monkeypatch):
    # Worker délibérément lent (bien plus long que le timeout de test) : sans
    # kill réel, le process survivrait largement à l'assertion ci-dessous.
    worker = _write_worker(tmp_path, """
        import sys, time
        time.sleep(30)
        with open(sys.argv[2], "w") as f:
            f.write("ne devrait jamais s'écrire")
    """)
    monkeypatch.setattr(pdf_adapter_module, "_WORKER_SCRIPT", worker)
    monkeypatch.setattr(pdf_adapter_module, "_PYMUPDF4LLM_TIMEOUT_S", 0.5)

    adapter = PDFAdapter()
    start = time.monotonic()
    result = asyncio.run(adapter._run_pymupdf4llm_subprocess(str(tmp_path / "doc.pdf")))
    elapsed = time.monotonic() - start

    assert result == ""
    # Le retour doit arriver proche du timeout (kill réel), pas attendre les 30s
    # du faux worker — c'est exactement ce qu'un thread orphelin ne garantirait pas.
    assert elapsed < 5


def test_subprocess_reussit_et_lit_le_resultat(tmp_path, monkeypatch):
    worker = _write_worker(tmp_path, """
        import sys
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write("# Titre\\ncontenu extrait")
    """)
    monkeypatch.setattr(pdf_adapter_module, "_WORKER_SCRIPT", worker)
    monkeypatch.setattr(pdf_adapter_module, "_PYMUPDF4LLM_TIMEOUT_S", 10)

    adapter = PDFAdapter()
    result = asyncio.run(adapter._run_pymupdf4llm_subprocess(str(tmp_path / "doc.pdf")))

    assert result == "# Titre\ncontenu extrait"


def test_subprocess_echec_worker_renvoie_vide(tmp_path, monkeypatch):
    worker = _write_worker(tmp_path, """
        import sys
        sys.exit(1)
    """)
    monkeypatch.setattr(pdf_adapter_module, "_WORKER_SCRIPT", worker)
    monkeypatch.setattr(pdf_adapter_module, "_PYMUPDF4LLM_TIMEOUT_S", 10)

    adapter = PDFAdapter()
    result = asyncio.run(adapter._run_pymupdf4llm_subprocess(str(tmp_path / "doc.pdf")))

    assert result == ""


def test_parse_bascule_sur_repli_si_pymupdf4llm_vide(tmp_path, monkeypatch):
    """parse() (bout-en-bout) : sous-processus qui échoue → repli texte/OCR appelé."""
    worker = _write_worker(tmp_path, """
        import sys
        sys.exit(1)
    """)
    monkeypatch.setattr(pdf_adapter_module, "_WORKER_SCRIPT", worker)
    monkeypatch.setattr(pdf_adapter_module, "_PYMUPDF4LLM_TIMEOUT_S", 10)
    monkeypatch.setattr(pdf_adapter_module, "_PYMUPDF4LLM_AVAILABLE", True)

    pdf_path = tmp_path / "doc.pdf"
    _make_text_pdf(pdf_path)  # texte réel : ne doit PAS être dévié par le triage scan

    adapter = PDFAdapter()
    monkeypatch.setattr(adapter, "_parse_fallback_sync", lambda file_path: "texte de repli")

    result = asyncio.run(adapter.parse(str(pdf_path)))

    assert result == "texte de repli"
