"""Tests des normaliseurs montants/dates (couche extraction, Phase 1)."""
from datetime import datetime

import pytest

from core.services.extraction.normalizers import parse_date, parse_montant


@pytest.mark.parametrize("raw, valeur, devise", [
    ("200M FCFA", 200_000_000.0, "XOF"),
    ("200 000 000 FCFA", 200_000_000.0, "XOF"),
    ("200.000.000", 200_000_000.0, "XOF"),
    ("1,2 Md", 1_200_000_000.0, "XOF"),
    ("200K", 200_000.0, "XOF"),
    ("1 234,56 €", 1_234.56, "EUR"),
    ("2 500 000 USD", 2_500_000.0, "USD"),
    (5_000_000, 5_000_000.0, "XOF"),
    (None, None, "XOF"),
    ("", None, "XOF"),
])
def test_parse_montant(raw, valeur, devise):
    v, d = parse_montant(raw)
    assert v == valeur
    assert d == devise


@pytest.mark.parametrize("raw, expected", [
    ("2024-06-30", datetime(2024, 6, 30)),
    ("2024-06", datetime(2024, 6, 1)),
    ("30/06/2024", datetime(2024, 6, 30)),
    ("15 mars 2024", datetime(2024, 3, 15)),
    ("mars 2024", datetime(2024, 3, 1)),
    ("2024", datetime(2024, 1, 1)),
    ("en cours", None),
    (None, None),
    ("", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected
