"""Worker isolé : convertit UN PDF en Markdown via pymupdf4llm, dans un
SOUS-PROCESSUS séparé — jamais importé/exécuté directement par le serveur.

Pourquoi un sous-processus et pas juste un thread (`asyncio.to_thread`) : un
document pathologique (tableaux très denses) peut faire dégénérer
`pymupdf4llm.to_markdown()` à plusieurs minutes (mesuré : 781s / 13 min sur un
cas réel). Un thread Python ne peut PAS être tué — passé un timeout, il reste
orphelin et continue de consommer un cœur CPU jusqu'à sa fin naturelle. Sur un
VPS partagé entre plusieurs projets clients (4 cœurs, 6 apps), ce cœur
monopolisé pendant de longues minutes dégrade les AUTRES apps de la machine,
pas seulement la nôtre. Un sous-processus, lui, peut être `kill()`é
immédiatement par le parent (`PDFAdapter._run_pymupdf4llm_subprocess`) —
libérant vraiment le CPU au moment du timeout, pas seulement la boucle
d'événements.

Usage : python _pymupdf4llm_worker.py <pdf_path> <output_path>
Écrit le Markdown dans <output_path> et sort en 0 si succès ; sort en 1 sans
rien écrire si l'import ou la conversion échoue (le parent traite ça comme
un pymupdf4llm indisponible — jamais d'exception qui remonte)."""
import sys


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    pdf_path, output_path = sys.argv[1], sys.argv[2]
    try:
        import pymupdf4llm
        markdown = pymupdf4llm.to_markdown(pdf_path) or ""
    except Exception:
        return 1
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
