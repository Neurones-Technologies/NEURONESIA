"""
Validation qualité du texte extrait avant indexation.

Si un document ne passe pas la validation, il est mis en quarantaine plutôt
qu'ignoré silencieusement. Règles :
- Longueur minimale absolue : 100 caractères
- Ratio texte/fichier : pour les PDF, au moins 0.8 char par Ko de fichier
  (un PDF de 100 Ko doit produire ≥ 80 chars — seuil très bas mais bloque les échecs OCR totaux)
- Pour les TXT/DOCX, seule la longueur absolue est vérifiée
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_MIN_CHARS = 100
_PDF_RATIO_CHARS_PER_KB = 0.8   # chars / Ko de fichier


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


class QualityValidator:
    def validate(self, text: str, file_path: Path) -> ValidationResult:
        warnings: list[str] = []
        text_len = len(text.strip())

        if text_len < _MIN_CHARS:
            return ValidationResult(
                is_valid=False,
                reason=f"Texte trop court : {text_len} caractères (minimum {_MIN_CHARS})",
            )

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            try:
                size_kb = file_path.stat().st_size / 1024
                if size_kb > 10:  # Ignorer les très petits fichiers
                    expected_min = size_kb * _PDF_RATIO_CHARS_PER_KB
                    if text_len < expected_min:
                        ratio = text_len / size_kb
                        return ValidationResult(
                            is_valid=False,
                            reason=(
                                f"Ratio texte/taille trop bas pour un PDF : "
                                f"{ratio:.1f} chars/Ko (minimum {_PDF_RATIO_CHARS_PER_KB}). "
                                f"OCR insuffisant ou fichier corrompu."
                            ),
                        )
            except OSError as exc:
                warnings.append(f"Impossible de lire la taille du fichier : {exc}")

        return ValidationResult(is_valid=True, warnings=warnings)
