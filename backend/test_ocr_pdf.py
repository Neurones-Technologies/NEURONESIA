"""
Test OCR autonome sur un PDF précis, via le vrai PDFAdapter de la GED.

Usage (depuis backend/, dans le venv) :
    python test_ocr_pdf.py
    python test_ocr_pdf.py "../data/ged/cvs/2021 - INCONNU - BEN Traore Formation CEH.PDF"
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

from adapters.parser import pdf_adapter
from adapters.parser.pdf_adapter import PDFAdapter

DEFAULT_PDF = "../data/ged/cvs/2021 - INCONNU - BEN Traore Formation CEH.PDF"


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF

    print("=" * 70)
    print(f"PyMuPDF (fitz) disponible : {pdf_adapter._FITZ_AVAILABLE}")
    print(f"Tesseract disponible      : {pdf_adapter._TESSERACT_AVAILABLE}")
    print(f"Fichier                   : {path}")
    print("=" * 70)

    if not (pdf_adapter._FITZ_AVAILABLE and pdf_adapter._TESSERACT_AVAILABLE):
        print("\n⚠️  OCR INACTIF : un PDF scanné restera vide.")
        print("    → Installe Tesseract (+ pack 'fra') et/ou pip install pymupdf pytesseract pillow,")
        print("    → puis relance ce script.\n")

    text = await PDFAdapter().parse(path)
    text = text.strip()

    print("\n" + "=" * 70)
    print(f"RÉSULTAT : {len(text)} caractères extraits, {len(text.split())} mots")
    print("=" * 70)
    if text:
        preview = text[:800]
        print(preview + ("…" if len(text) > 800 else ""))
    else:
        print("(aucun texte — extraction échouée sur les 3 méthodes)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
