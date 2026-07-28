"""
Diagnostic d'extraction PDF — pourquoi un AO scanné ne donne que des tirets.

Usage (depuis backend/, avec le venv) :
    .venv/Scripts/python.exe diagnose_pdf.py "C:/chemin/vers/mon-AO-scanne.pdf"

Montre, page par page : le nombre de caractères extraits (couche texte), si la page
est jugée « maigre » (→ OCR) ou « texte OK » (→ OCR SAUTÉ), puis ce que l'OCR forcé
récupérerait, et enfin le texte final réellement envoyé au pipeline LLM.
"""
import asyncio
import sys
from pathlib import Path

from config.settings import settings
from adapters.parser import pdf_adapter as pa
from adapters.parser.pdf_adapter import PDFAdapter
from adapters.parser.markdown_fidelity import alnum_count, is_faithful


async def main(path: str) -> None:
    print(f"Fichier : {path}")
    print(f"Taille  : {Path(path).stat().st_size / 1024 / 1024:.1f} Mo")
    print(
        f"OCR dispo -> fitz={pa._FITZ_AVAILABLE} tesseract={pa._TESSERACT_AVAILABLE} "
        f"langs={pa._OCR_LANGS} pymupdf4llm={pa._PYMUPDF4LLM_AVAILABLE}"
    )
    print(
        f"Seuils -> ocr_min_chars_per_page={settings.ocr_min_chars_per_page} "
        f"ocr_max_pages={settings.ocr_max_pages}"
    )
    ad = PDFAdapter()

    # 1) Étape 0 du parser : pymupdf4llm → Markdown (et est-il jugé « fidèle » donc retourné ?)
    md = ad._try_pymupdf4llm(path)
    print(f"\n[pymupdf4llm] markdown len={len(md)}")
    if md:
        base = ad._plain_text_baseline(path)
        print(
            f"  baseline len={len(base)} | md alnum={alnum_count(md)} "
            f"base alnum={alnum_count(base)} | RETOURNÉ_DIRECT(faithful)={is_faithful(md, base)}"
        )

    # 2) Couche texte par page (pdfplumber vs PyMuPDF) + décision OCR
    plumber = ad._pdfplumber_pages(path)
    mupdf = ad._pymupdf_pages(path) if pa._FITZ_AVAILABLE else []
    n = max(len(plumber), len(mupdf))
    print(f"\n[pages] total={n}")
    thin = []
    for i in range(n):
        p = plumber[i] if i < len(plumber) else ""
        m = mupdf[i] if i < len(mupdf) else ""
        best = m if len(m) > len(p) else p
        nc = len(best.strip())
        if nc < settings.ocr_min_chars_per_page:
            thin.append(i)
            flag = "MAIGRE -> OCR"
        else:
            flag = "texte-ok -> OCR SAUTÉ"
        preview = " ".join(best.strip().split())[:70]
        print(f"  page {i:2d}: chars={nc:5d}  {flag:22s}  {preview!r}")
    skipped = [i for i in range(n) if i not in thin]
    print(f"\n[décision] OCR sur pages {thin}")
    print(f"           OCR SAUTÉ (jugées texte-ok) sur pages {skipped}")

    # 3) OCR FORCÉ sur toutes les pages : preuve que l'OCR sait lire ce fichier
    print("\n[OCR forcé sur toutes les pages] (peut prendre du temps)…")
    ocr = ad._ocr_pages(path, list(range(n)))
    tot = sum(len(v) for v in ocr.values())
    print(f"  OCR a produit {tot} chars sur {len(ocr)} page(s)")
    if ocr:
        k = sorted(ocr)[0]
        print(f"  extrait OCR (page {k}) : {' '.join(ocr[k].split())[:300]!r}")

    # 4) parse() complet = EXACTEMENT ce que le pipeline envoie au LLM
    print("\n[parse() complet — ce que le pipeline envoie réellement au LLM]…")
    txt = await ad.parse(path)
    alnum = sum(c.isalnum() for c in txt)
    print(f"  longueur finale={len(txt)}  caractères alphanumériques={alnum}")
    print(f"  extrait : {' '.join(txt.split())[:400]!r}")
    print("\n=== VERDICT ===")
    if alnum < 200:
        print("  Le pipeline reçoit un texte QUASI VIDE → d'où la réponse « uniquement des tirets ».")
    if skipped and tot > alnum * 2:
        print("  L'OCR forcé récupère BEAUCOUP plus que la couche texte : des pages scannées")
        print("  ont été jugées « texte-ok » à tort (pointillés/pieds de page > seuil) et l'OCR sauté.")
        print("  → FIX : forcer l'OCR pour ces pages (baisser le seuil OU détecter les pages 'pointillés').")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage : .venv/Scripts/python.exe diagnose_pdf.py "C:/chemin/AO.pdf"')
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
