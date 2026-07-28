import logging

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from core.ports.document_parser import DocumentParser
from adapters.parser.docx_markdown import (
    heading_level,
    is_bullet_style,
    grid_to_markdown,
    strip_control,
)

logger = logging.getLogger(__name__)


class DocxAdapter(DocumentParser):
    """
    Extraction Word (.docx) → Markdown (titres #, listes -, tableaux |…|), en
    préservant l'ordre de lecture (paragraphes et tableaux entrelacés comme dans
    le document). Repli sur l'extraction texte plat historique si la conversion échoue.
    """

    async def parse(self, file_path: str) -> str:
        try:
            doc = DocxDocument(file_path)
        except Exception as e:
            logger.warning("Erreur ouverture DOCX %s: %s", file_path, e)
            return ""

        # Markdown structuré (préserve titres/listes/tableaux + ordre de lecture)
        try:
            md = self._to_markdown(doc)
            if md.strip():
                logger.info("DOCX → Markdown (%d caractères) : %s", len(md), file_path)
                return strip_control(md)
        except Exception as e:
            logger.warning("DOCX → Markdown échoué (%s) — repli texte plat : %s", e, file_path)

        # Repli : extraction texte plat (comportement historique, jamais de perte)
        return strip_control(self._plain_text(doc))

    # ── Markdown ─────────────────────────────────────────────────────────────

    def _to_markdown(self, doc) -> str:
        parts: list[str] = []
        for block in self._iter_blocks(doc):
            if isinstance(block, Paragraph):
                line = self._paragraph_md(block)
                if line:
                    parts.append(line)
            elif isinstance(block, Table):
                table_md = grid_to_markdown(self._table_grid(block))
                if table_md:
                    parts.append(table_md)
        return "\n\n".join(parts)

    @staticmethod
    def _paragraph_md(p: Paragraph) -> str:
        text = p.text.strip()
        if not text:
            return ""
        try:
            style_name = p.style.name if p.style else ""
        except Exception:
            style_name = ""
        level = heading_level(style_name)
        if level:
            return "#" * level + " " + text
        if is_bullet_style(style_name):
            return "- " + text
        return text

    @staticmethod
    def _table_grid(table: Table) -> list[list[str]]:
        return [[cell.text for cell in row.cells] for row in table.rows]

    @staticmethod
    def _iter_blocks(doc):
        """Itère paragraphes et tables DANS L'ORDRE du document (préserve le contexte)."""
        body = doc.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, doc)
            elif child.tag == qn("w:tbl"):
                yield Table(child, doc)

    # ── Repli texte plat (historique) ─────────────────────────────────────────

    @staticmethod
    def _plain_text(doc) -> str:
        parts: list[str] = []
        for p in doc.paragraphs:
            text = p.text.strip()
            if text:
                parts.append(text)

        # Tableaux (dédoublonnage des cellules fusionnées)
        for table in doc.tables:
            seen_cells: set[str] = set()
            for row in table.rows:
                row_cells = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text and cell_text not in seen_cells:
                        row_cells.append(cell_text)
                        seen_cells.add(cell_text)
                if row_cells:
                    parts.append(" | ".join(row_cells))
        return "\n\n".join(parts)

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith((".docx", ".doc"))
