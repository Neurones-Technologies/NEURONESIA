"""
Persistance de la matrice de conformité (UC10 Pre-Sales) — clôture du « trou C5 ».

Avant : les validations humaines (statut, domaine validé, commentaire) saisies dans
l'Excel exporté n'étaient JAMAIS re-persistées → ré-générer la matrice repartait des
défauts IA, aucun historique, aucun contrôle auditable.

Ici : un fichier JSON par AO (nommé par SHA-256 de `ao_filename`) sous `data/matrix_store/`.
Aucune dépendance externe (même approche que le cache de score). `apply_confirmations`
est PUR (load/merge/save séparés) → testable hors disque via `base`.

`save`/`load`/`confirm` acceptent `base` (dossier racine) pour les tests ; défaut = settings.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from config.settings import settings
from core.domain.requirements import MatriceConformite, STATUTS_CONFORMITE, STATUT_CONFORME


def _default_base() -> Path:
    return Path(settings.uploads_path).parent / "matrix_store"


def default_base() -> Path:
    """Dossier racine du store (exposé pour la purge LRU côté router)."""
    return _default_base()


def _key(ao_filename: str) -> str:
    return hashlib.sha256((ao_filename or "").encode("utf-8")).hexdigest()


def store_path(ao_filename: str, base: Path | None = None) -> Path:
    return (Path(base) if base else _default_base()) / f"{_key(ao_filename)}.json"


def save(matrice: MatriceConformite, base: Path | None = None) -> Path:
    """Écrit la matrice (incluant les validations humaines déjà présentes) en JSON."""
    path = store_path(matrice.ao_filename, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(matrice.to_json(), encoding="utf-8")
    return path


def load(ao_filename: str, base: Path | None = None) -> MatriceConformite | None:
    """Recharge la matrice persistée d'un AO, ou None si absente/illisible."""
    path = store_path(ao_filename, base)
    if not path.exists():
        return None
    try:
        return MatriceConformite.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def apply_confirmations(
    matrice: MatriceConformite,
    confirmations: list[dict],
    *,
    confirme_par: str = "",
    now_iso: str = "",
) -> MatriceConformite:
    """Applique les cochages humains à la matrice (en place) et la renvoie. PUR.

    Chaque confirmation = dict {id, statut_confirme?, domaine_valide?, commentaire?, confirme?}.
    Cocher (`confirme` truthy, défaut True) FIGE le contrôle humain :
      - `statut_conformite` ← `statut_confirme` (validé) si fourni et licite, sinon CONFORME ;
      - `confirme=True`, `confirme_par`, `confirme_le=now_iso`.
    `confirme=False` lève la confirmation (retour à A_TRAITER, traçabilité effacée).
    Les ids inconnus sont ignorés (jamais d'exception).
    """
    by_id = {ex.id: ex for ex in matrice.exigences}
    for conf in confirmations or []:
        ex = by_id.get(str(conf.get("id", "")))
        if ex is None:
            continue
        if "domaine_valide" in conf and conf["domaine_valide"] is not None:
            ex.domaine_valide = str(conf["domaine_valide"]).strip()
        if "commentaire" in conf and conf["commentaire"] is not None:
            ex.commentaire = str(conf["commentaire"]).strip()

        ticked = conf.get("confirme", True)
        if ticked:
            statut = str(conf.get("statut_confirme") or "").strip().upper()
            ex.statut_conformite = statut if statut in STATUTS_CONFORMITE else STATUT_CONFORME
            ex.confirme = True
            ex.confirme_par = confirme_par
            ex.confirme_le = now_iso
        else:
            ex.statut_conformite = "A_TRAITER"
            ex.confirme = False
            ex.confirme_par = ""
            ex.confirme_le = ""
    return matrice


def confirm(
    ao_filename: str,
    confirmations: list[dict],
    *,
    confirme_par: str = "",
    now_iso: str = "",
    base: Path | None = None,
) -> MatriceConformite | None:
    """Charge la matrice persistée, applique les cochages, re-sauvegarde, renvoie la matrice.

    Renvoie None si aucune matrice n'a été persistée pour cet AO (il faut /matrix/assess avant).
    """
    matrice = load(ao_filename, base)
    if matrice is None:
        return None
    apply_confirmations(matrice, confirmations, confirme_par=confirme_par, now_iso=now_iso)
    save(matrice, base)
    return matrice
