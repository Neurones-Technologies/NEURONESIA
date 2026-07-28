"""Persistance du briefing quotidien — gelé jusqu'à la régénération planifiée
(minuit) ou une relance manuelle. Même pattern que uc10_presales/matrix_store.py :
un fichier JSON sous data/, fonctions pures load/save acceptant un `base`
optionnel pour rester testables hors disque.
"""
from __future__ import annotations

import json
from pathlib import Path

from config.settings import settings


def _default_base() -> Path:
    return Path(settings.uploads_path).parent / "briefing_store"


def default_base() -> Path:
    """Dossier racine du store (exposé pour d'éventuels besoins d'inspection)."""
    return _default_base()


def _path(base: Path | None = None) -> Path:
    return (Path(base) if base else _default_base()) / "latest.json"


def save(payload: dict, base: Path | None = None) -> Path:
    path = _path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(base: Path | None = None) -> dict | None:
    """Recharge le snapshot gelé, ou None si absent/illisible (premier démarrage)."""
    path = _path(base)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
