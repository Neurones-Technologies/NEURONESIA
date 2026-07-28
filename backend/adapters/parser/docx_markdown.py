"""
Rendu Markdown pour DOCX (POC parsing GED) — fonctions pures, sans dépendance à python-docx.

Permet de tester la logique de rendu (titres, listes, tableaux) sans ouvrir un vrai fichier
Word. L'adapter (docx_adapter.py) fait l'extraction python-docx puis délègue le rendu ici.
"""
import re

_HEADING_RE = re.compile(r"(?:heading|titre)\s*(\d+)", re.IGNORECASE)


def heading_level(style_name: str) -> int:
    """
    Niveau de titre Markdown (1-6) d'après le style de paragraphe Word, sinon 0.
    Gère l'anglais ('Heading 2', 'Title') et le français ('Titre 2', 'Titre').
    """
    name = (style_name or "").strip().lower()
    m = _HEADING_RE.match(name)
    if m:
        return min(int(m.group(1)), 6)
    if name in ("title", "titre"):
        return 1
    return 0


def is_bullet_style(style_name: str) -> bool:
    """True si le style correspond à une liste à puces (EN/FR)."""
    name = (style_name or "").lower()
    return "bullet" in name or "puce" in name


def md_cell(text: str) -> str:
    """Normalise une cellule pour une table Markdown : pas de retour ligne, pipe échappé."""
    return (text or "").strip().replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def grid_to_markdown(grid: list[list[str]]) -> str:
    """
    Convertit une grille de cellules en table Markdown (1re ligne = en-tête).
    Les lignes plus courtes sont complétées pour garder des colonnes alignées.
    """
    rows = [r for r in grid if r]
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    norm = [[md_cell(c) for c in r] + [""] * (ncols - len(r)) for r in rows]
    lines = [
        "| " + " | ".join(norm[0]) + " |",
        "| " + " | ".join(["---"] * ncols) + " |",
    ]
    for r in norm[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def strip_control(text: str) -> str:
    """Retire les caractères de contrôle non imprimables (conserve \\n et \\t)."""
    return "".join(ch for ch in text if ch >= " " or ch in "\n\t")
