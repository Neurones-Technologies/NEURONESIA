"""Couche C — taxonomie MINIMALE de matching AO ↔ Odoo (garde-fou déterministe).

Ne porte aucune logique métier de thème (cela revient au sémantique + LLM). Trois
fonctions seulement, adossées à `data/taxonomy/odoo_matching.yaml` :

  - normalize_product()   : code produit brut → libellé lisible
  - is_hardware_dominated(): True si l'affaire est manifestement matérielle (anti-bruit)
  - find_critical_terms() : termes éliminatoires/critiques présents dans un texte

Le fichier YAML est éditable par l'avant-vente sans redéploiement.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

from config.settings import settings

logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(settings.uploads_path).parent / "taxonomy" / "odoo_matching.yaml"


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _norm(text: str) -> str:
    """Minuscule + sans accents — base de toutes les comparaisons."""
    return _strip_accents((text or "").lower())


@lru_cache(maxsize=1)
def load_taxonomy() -> dict:
    """Charge le YAML une fois. En cas d'absence/illisibilité, renvoie un garde-fou vide
    (l'enrichissement reste fonctionnel, sans normalisation ni exclusion)."""
    try:
        data = yaml.safe_load(_TAXONOMY_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Taxonomie Odoo illisible (%s) — garde-fou vide", exc)
        data = {}
    data.setdefault("exclusions", {}).setdefault("hardware_markers", [])
    data.setdefault("product_normalization", [])
    data.setdefault("critical_terms", [])
    return data


def normalize_product(raw: str) -> str:
    """Code/libellé produit brut → libellé lisible (ex: 'F5-SVC-BIG-VE' → 'F5 BIG-IP').

    Si aucun mapping ne matche, renvoie le libellé nettoyé (tronqué, sans codes parasites)."""
    if not raw:
        return ""
    n = _norm(raw)
    for rule in load_taxonomy()["product_normalization"]:
        if re.search(rule["match"], n):
            return rule["label"]
    # repli : garder la partie lisible (avant tabulation/code), tronquée
    cleaned = re.split(r"[\t#]", raw, maxsplit=1)[0].strip().rstrip(":").strip()
    return cleaned[:40] if cleaned else ""


def is_hardware_dominated(text: str) -> bool:
    """True si le texte contient un marqueur matériel (SFP, jarretière, catalyst…).

    Sert à bloquer le classement d'une affaire matérielle dans un thème logiciel/Odoo.
    """
    n = _norm(text)
    return any(_norm(m) in n for m in load_taxonomy()["exclusions"]["hardware_markers"])


def find_critical_terms(text: str) -> list[dict]:
    """Termes critiques/éliminatoires présents dans le texte (FNE, SYSCOHADA, ISO 27001…)."""
    n = _norm(text)
    found = []
    for ct in load_taxonomy()["critical_terms"]:
        if _norm(ct["term"]) in n:
            found.append(ct)
    return found
