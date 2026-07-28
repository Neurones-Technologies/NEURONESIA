"""Test de la correction de troncature sur un AO réel.

Compare ce que le LLM voyait AVANT (ao_text[:5000]) vs MAINTENANT
(_truncate_by_tokens à 100K tokens). Ne fait AUCUN appel LLM payant —
on vérifie juste que l'info clé n'est plus coupée.
"""
import asyncio
import logging
import re
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

from adapters.parser.pdf_adapter import PDFAdapter
from adapters.llm.claude_haiku_adapter import ClaudeHaikuAdapter
from modules.uc10_presales.scoring_pipeline import (
    _truncate_by_tokens,
    _EXTRACT_INPUT_BUDGET_TOKENS,
    _SUMMARY_INPUT_BUDGET_TOKENS,
    _ANALYZE_INPUT_BUDGET_TOKENS,
)

PDF_PATH = r"C:\Users\Soro Landry\Downloads\Data\CV\Cahier des Charges_ TABLEAU DE BORD 2026 VF.pdf"

# Marqueurs typiques d'un AO — leur position révèle si la troncature 5000 chars les coupait
MARKERS = [
    r"date\s+limite",
    r"date\s+de\s+remise",
    r"deadline",
    r"pond[ée]ration",
    r"crit[èe]re.{0,30}(technique|financier)",
    r"\b\d{1,3}\s*%",                         # % (pondération)
    r"valid[ie]t[ée]\s+de\s+l[''']\s*offre",
    r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*20\d{2}",   # date format JJ/MM/AAAA
    r"NEEMBA",
    r"d[ée]marrage",
]


async def main():
    print("=" * 70)
    print(f"Parse : {PDF_PATH}")
    print("=" * 70)
    parser = PDFAdapter()
    text = await parser.parse(PDF_PATH)
    if not text:
        print("ERREUR : aucun texte extrait du PDF")
        sys.exit(1)

    llm = ClaudeHaikuAdapter.__new__(ClaudeHaikuAdapter)
    # Bypass __init__ pour éviter d'instancier le client Anthropic (pas besoin de clé API
    # pour count_tokens — il n'utilise que tiktoken local).
    import tiktoken
    llm._encoder = tiktoken.get_encoding("cl100k_base")

    total_chars = len(text)
    total_tokens = llm.count_tokens(text)
    print(f"\nDocument extrait : {total_chars:,} chars, {total_tokens:,} tokens")

    # --- AVANT (ancienne troncature) ---
    old_extract = text[:5000]
    old_summary = text[:6000]
    old_analyze = text[:3000]
    print(f"\n[AVANT le fix]")
    print(f"  _step1_extract voyait : {len(old_extract):,} chars (~{llm.count_tokens(old_extract):,} tokens)")
    print(f"  _step2_summarize voyait : {len(old_summary):,} chars")
    print(f"  _step4_analyze voyait : {len(old_analyze):,} chars")
    print(f"  => {(1 - 5000/total_chars)*100:.1f}% du document était IGNORÉ par l'extraction")

    # --- MAINTENANT (nouveau budget) ---
    new_extract = _truncate_by_tokens(text, llm, _EXTRACT_INPUT_BUDGET_TOKENS, step="extract")
    new_summary = _truncate_by_tokens(text, llm, _SUMMARY_INPUT_BUDGET_TOKENS, step="summarize")
    new_analyze = _truncate_by_tokens(text, llm, _ANALYZE_INPUT_BUDGET_TOKENS, step="analyze")
    print(f"\n[APRÈS le fix]")
    print(f"  _step1_extract voit : {len(new_extract):,} chars (~{llm.count_tokens(new_extract):,} tokens)")
    print(f"  _step2_summarize voit : {len(new_summary):,} chars")
    print(f"  _step4_analyze voit : {len(new_analyze):,} chars")
    if len(new_extract) == total_chars:
        print(f"  => Document ENTIER vu par le LLM (pas de troncature)")
    else:
        print(f"  => {(len(new_extract)/total_chars)*100:.1f}% du document vu par le LLM")

    # --- Où sont les infos clés ? ---
    print(f"\n{'=' * 70}")
    print("Position des marqueurs critiques dans le texte")
    print("=" * 70)
    print(f"{'Marqueur':<35} {'Position':>10} {'Coupé à 5000?':>15}")
    print("-" * 70)
    found_after_5000 = []
    for pattern in MARKERS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            pos = m.start()
            cut = "OUI (perdu)" if pos >= 5000 else "non"
            print(f"{pattern:<35} {pos:>10,} {cut:>15}")
            if pos >= 5000:
                found_after_5000.append((pattern, pos, m.group(0)[:60]))
        else:
            print(f"{pattern:<35} {'non trouvé':>10} {'-':>15}")

    # --- Verdict ---
    print(f"\n{'=' * 70}")
    print("VERDICT")
    print("=" * 70)
    if found_after_5000:
        print(f"\n{len(found_after_5000)} marqueur(s) critique(s) tombaient APRÈS le caractère 5000 :")
        for pattern, pos, match in found_after_5000:
            print(f"  - '{pattern}' à pos {pos:,} (extrait: '{match}...')")
        print("\n=> Le LLM ne pouvait pas les voir avant le fix. Hallucination probable.")
        print("=> Avec le nouveau budget, ils sont dans la fenetre du LLM.")
    else:
        print("\nTous les marqueurs trouvés étaient dans les 5000 premiers chars.")
        print("(Ce PDF n'est peut-être pas un AO long classique — ou structure inhabituelle)")

    # Extrait de ce qui était PERDU (entre 5000 et fin) — premiers 800 chars
    if total_chars > 5000:
        lost = text[5000:5800]
        print(f"\n--- Extrait de ce que le LLM NE voyait PAS (chars 5000-5800) ---")
        print(lost)
        print("---")


if __name__ == "__main__":
    asyncio.run(main())
