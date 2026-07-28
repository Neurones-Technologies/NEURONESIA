"""
Normalisation des montants et des dates extraits par le LLM.

Objectif (cf. playbook §7) : « 200M », « 200 000 000 FCFA », « 200.000.000 »
doivent tous finir dans une colonne numérique unique, avec la devise à part ;
les dates FR/ISO variées doivent finir en `datetime` pour les filtres
« > X FCFA » et « N dernières années ».
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple

# ── Montants ─────────────────────────────────────────────────────────────────

DEFAULT_DEVISE = "XOF"

# FCFA et XOF désignent la même devise — on canonicalise en XOF.
_DEVISE_PATTERNS = [
    (re.compile(r"(€|\beuros?\b|\beur\b)", re.I), "EUR"),
    (re.compile(r"(\$|\busd\b|\bdollars?\b)", re.I), "USD"),
    (re.compile(r"\b(mad|dirhams?)\b", re.I), "MAD"),
    (re.compile(r"\b(fcfa|f\.?\s?cfa|xof|francs?\s*cfa|francs?\b)\b", re.I), "XOF"),
]

# Multiplicateurs textuels / suffixes, du plus grand au plus petit.
_MULTIPLIERS = [
    (re.compile(r"(\d[\d ., ]*)\s*(?:milliards?|mds?|b)\b", re.I), 1_000_000_000),
    (re.compile(r"(\d[\d ., ]*)\s*(?:millions?|m)\b", re.I), 1_000_000),
    (re.compile(r"(\d[\d ., ]*)\s*(?:milliers?|k)\b", re.I), 1_000),
]


def detect_devise(s: str, default: str = DEFAULT_DEVISE) -> str:
    for pattern, devise in _DEVISE_PATTERNS:
        if pattern.search(s):
            return devise
    return default


def _to_float_simple(token: str) -> Optional[float]:
    """Pour une base accompagnée d'un multiplicateur (ex. « 1,5 » dans « 1,5 Md »)."""
    t = token.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if t.count(".") > 1:  # « 1.234 » improbable ici, on garde le dernier point
        parts = t.split(".")
        t = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(t)
    except ValueError:
        return None


def _parse_plain_number(s: str) -> Optional[float]:
    """Extrait un nombre avec séparateurs FR/EN sans multiplicateur."""
    m = re.search(r"\d[\d ., ]*\d|\d", s)
    if not m:
        return None
    tok = m.group(0).replace(" ", " ").strip().replace(" ", "")
    has_dot, has_comma = "." in tok, "," in tok

    if has_dot and has_comma:
        # Le dernier séparateur rencontré est le séparateur décimal.
        if tok.rfind(".") > tok.rfind(","):
            tok = tok.replace(",", "")               # virgule = milliers
        else:
            tok = tok.replace(".", "").replace(",", ".")  # point = milliers
    elif has_comma:
        if tok.count(",") == 1 and len(tok.split(",")[1]) in (1, 2):
            tok = tok.replace(",", ".")              # décimale
        else:
            tok = tok.replace(",", "")               # milliers
    elif has_dot:
        if tok.count(".") == 1 and len(tok.split(".")[1]) in (1, 2):
            pass                                     # décimale
        else:
            tok = tok.replace(".", "")               # milliers
    try:
        return float(tok)
    except ValueError:
        return None


def parse_montant(
    raw, default_devise: str = DEFAULT_DEVISE
) -> Tuple[Optional[float], str]:
    """
    Renvoie (valeur_numerique, devise). La valeur est en unités entières
    (200M → 200000000.0). La devise par défaut est XOF si non détectée.
    """
    if raw is None:
        return None, default_devise
    if isinstance(raw, (int, float)):
        return float(raw), default_devise

    s = str(raw).strip()
    if not s:
        return None, default_devise

    devise = detect_devise(s, default_devise)

    for pattern, mult in _MULTIPLIERS:
        m = pattern.search(s)
        if m:
            base = _to_float_simple(m.group(1))
            if base is not None:
                return base * mult, devise

    return _parse_plain_number(s), devise


# ── Dates ────────────────────────────────────────────────────────────────────

_FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

_EMPTY_DATE = {"", "en cours", "présent", "present", "n/a", "na", "null", "none", "inconnu", "-"}


def _safe_date(year: int, month: int, day: int) -> Optional[datetime]:
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def parse_date(raw) -> Optional[datetime]:
    """
    Convertit une date ISO/FR variée en `datetime` (minuit). Renvoie None si
    absente, « en cours » ou non interprétable.
    """
    if raw is None or isinstance(raw, datetime):
        return raw
    s = str(raw).strip().lower()
    if s in _EMPTY_DATE:
        return None

    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)          # ISO complet
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = re.fullmatch(r"(\d{4})-(\d{2})", s)               # YYYY-MM
    if m:
        return _safe_date(int(m[1]), int(m[2]), 1)

    m = re.match(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", s)  # dd/mm/yyyy
    if m:
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))

    for name, num in _FRENCH_MONTHS.items():              # « 15 mars 2024 »
        if re.search(rf"\b{re.escape(name)}", s):
            ym = re.search(r"\b(\d{4})\b", s)
            if not ym:
                return None
            year = int(ym.group(1))
            rest = s.replace(ym.group(1), " ", 1)
            dm = re.search(r"\b(\d{1,2})\b", rest)
            day = int(dm.group(1)) if dm else 1
            return _safe_date(year, num, day)

    m = re.fullmatch(r"(\d{4})", s)                       # année seule
    if m:
        return _safe_date(int(m[1]), 1, 1)

    return None
