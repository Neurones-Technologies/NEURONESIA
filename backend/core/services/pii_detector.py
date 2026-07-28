"""
Détection de données personnelles (PII) dans les documents.

Utilisé principalement sur les CV (RGPD critique).
Ne supprime PAS le contenu — les CV ont besoin de leurs données pour être utiles.
Produit un rapport qui :
  1. Tague le document comme contenant des PII
  2. Liste les catégories détectées (pour l'audit et le filtrage d'accès)

Droit à l'oubli : propagé via GEDIndexer.remove() qui purge les vecteurs.
Le PIIDetector ne gère que la détection, pas la suppression.
"""
import re
from dataclasses import dataclass, field

# ── Patterns regex (contexte France/Afrique francophone) ────────────────────

# Numéro de Sécurité Sociale français (NIR) : 13 chiffres + 2 chiffres clé
_RE_NSS = re.compile(
    r'\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2]|[2-9]\d)\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\b'
)

# IBAN français
_RE_IBAN = re.compile(
    r'\bFR\d{2}\s?(?:[0-9A-Z]{4}\s?){4}[0-9A-Z]{1,4}\b', re.IGNORECASE
)

# Email
_RE_EMAIL = re.compile(
    r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'
)

# Téléphone français / Afrique de l'Ouest
_RE_PHONE = re.compile(
    r'\b(?:'
    r'(?:\+33|0033|0)[1-9](?:[\s.\-]?\d{2}){4}'   # France : +33 / 0033 / 0X
    r'|(?:\+225|00225)\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{2}'  # Côte d'Ivoire
    r'|(?:\+221|00221)\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}'  # Sénégal
    r')\b'
)

# Date de naissance explicite ("né le", "date de naissance")
_RE_DOB = re.compile(
    r'(?:né(?:e)?\s+le|date\s+de\s+naissance\s*:?)\s*\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}',
    re.IGNORECASE,
)

_DETECTORS = [
    ("nss", _RE_NSS),
    ("iban", _RE_IBAN),
    ("email", _RE_EMAIL),
    ("phone", _RE_PHONE),
    ("date_naissance", _RE_DOB),
]


@dataclass
class PIIReport:
    has_pii: bool
    categories: list[str] = field(default_factory=list)


class PIIDetector:
    def detect(self, text: str) -> PIIReport:
        found: list[str] = []
        for category, pattern in _DETECTORS:
            if pattern.search(text):
                found.append(category)
        return PIIReport(has_pii=bool(found), categories=found)
