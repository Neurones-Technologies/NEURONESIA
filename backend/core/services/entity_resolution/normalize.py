"""
Normalisation des libellés d'entités avant appariement.

But : « SGBCI SA », « S.G.B.C.I. » et « sgbci » doivent produire la même clé.
Pour les clients, on retire en plus les formes juridiques (SA, SARL…) qui ne
discriminent pas l'entité.
"""
from __future__ import annotations

import re
import unicodedata

# Formes juridiques retirées pour les clients (bruit non discriminant).
_LEGAL_FORMS = {
    "sa", "sarl", "sas", "sasu", "eurl", "gie", "sci", "snc", "scs",
    "ltd", "llc", "inc", "plc", "spa", "gmbh", "ag", "co", "cie",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _collapse_single_letters(tokens: list[str]) -> list[str]:
    """Fusionne les suites de ≥2 lettres isolées : « s g b c i » → « sgbci »,
    « s a » → « sa » (utile pour les sigles pointés et les formes juridiques).
    Une lettre isolée seule (ex. le « d » de « d information ») est conservée.
    """
    out: list[str] = []
    run: list[str] = []
    for t in tokens:
        if len(t) == 1:
            run.append(t)
            continue
        if run:
            out.append("".join(run) if len(run) >= 2 else run[0])
            run = []
        out.append(t)
    if run:
        out.append("".join(run) if len(run) >= 2 else run[0])
    return out


def _base(s: str) -> str:
    s = _strip_accents(str(s)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(_collapse_single_letters(s.split()))


def normalize(label, entity_type: str) -> str:
    """Renvoie la clé normalisée d'un libellé pour le type d'entité donné."""
    if label is None:
        return ""
    base = _base(label)
    if entity_type == "client" and base:
        tokens = [t for t in base.split() if t not in _LEGAL_FORMS]
        base = " ".join(tokens) or base
    return base
