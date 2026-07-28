from abc import ABC, abstractmethod


class DocumentParser(ABC):
    """Interface pour l'extraction de texte depuis un fichier (PDF, Word, etc.)."""

    @abstractmethod
    async def parse(self, file_path: str) -> str:
        """Extrait le texte brut d'un fichier. Retourne une chaîne vide si non lisible."""

    @abstractmethod
    def supports(self, file_path: str) -> bool:
        """Retourne True si ce parser prend en charge l'extension du fichier."""
