from abc import ABC, abstractmethod
from pathlib import Path

from core.domain.document import DocumentType


class DocumentStorage(ABC):
    """Interface pour accéder aux fichiers de la GED."""

    @abstractmethod
    def list_files(self, doc_type: DocumentType | None = None) -> list[Path]:
        """Liste les fichiers de la GED, filtrés par type si spécifié."""

    @abstractmethod
    def get_file_bytes(self, file_path: Path) -> bytes:
        """Lit le contenu binaire d'un fichier."""

    @abstractmethod
    def save_file(self, category: str, filename: str, content: bytes) -> Path:
        """Sauvegarde un fichier dans la GED et retourne son chemin."""

    @abstractmethod
    def infer_doc_type(self, file_path: Path) -> DocumentType:
        """Déduit le type de document depuis le chemin (dossier parent)."""
