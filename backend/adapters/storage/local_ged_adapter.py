import logging
from pathlib import Path

from core.ports.document_storage import DocumentStorage
from core.domain.document import DocumentType
from config.settings import settings

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "cvs": DocumentType.CV,
    "offres-techniques": DocumentType.OFFRE_TECHNIQUE,
    "abe": DocumentType.ABE,
    "pv-recette": DocumentType.PV_RECETTE,
    "procedures": DocumentType.PROCEDURE,
    "fiches-techniques": DocumentType.FICHE_TECHNIQUE,
    "comptes-rendus": DocumentType.COMPTE_RENDU,
    "marches-similaires": DocumentType.MARCHES_SIMILAIRES,
}

_SUPPORTED_EXT = {".pdf", ".docx", ".doc", ".txt"}


class LocalGEDAdapter(DocumentStorage):
    """Accès au système de fichiers GED local (data/ged/)."""

    def __init__(self):
        self._ged_root = Path(settings.ged_path)

    def list_files(self, doc_type: DocumentType | None = None) -> list[Path]:
        files = []
        if doc_type:
            folders = [k for k, v in _TYPE_MAP.items() if v == doc_type]
        else:
            folders = list(_TYPE_MAP.keys())

        for folder in folders:
            folder_path = self._ged_root / folder
            if folder_path.exists():
                for f in folder_path.rglob("*"):
                    if f.is_file() and f.suffix.lower() in _SUPPORTED_EXT:
                        files.append(f)
        return files

    def get_file_bytes(self, file_path: Path) -> bytes:
        return file_path.read_bytes()

    def save_file(self, category: str, filename: str, content: bytes) -> Path:
        dest_dir = self._ged_root / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        dest.write_bytes(content)
        logger.info("Fichier sauvegardé dans GED : %s", dest)
        return dest

    def infer_doc_type(self, file_path: Path) -> DocumentType:
        for part in file_path.parts:
            if part in _TYPE_MAP:
                return _TYPE_MAP[part]
        return DocumentType.UNKNOWN
