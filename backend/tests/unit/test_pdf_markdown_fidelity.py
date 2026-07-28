"""Tests du garde-fou de fidélité PDF → Markdown (POC parsing GED)."""
import pytest

from adapters.parser.markdown_fidelity import alnum_count as _alnum_count, is_faithful as _is_faithful


@pytest.mark.parametrize("text, expected", [
    ("", 0),
    ("Hello, World!", 10),
    ("## Titre | col |", 8),   # symboles Markdown ignorés
    ("éà9", 3),                 # accents + chiffres comptés
])
def test_alnum_count(text, expected):
    assert _alnum_count(text) == expected


def test_faithful_markdown_preserves_content():
    """Le Markdown ajoute des symboles mais conserve le texte → accepté."""
    baseline = "Le routeur coute mille euros " * 20
    markdown = "## Equipements\n\n" + "| Le routeur | coute | mille euros |\n" * 20
    assert _is_faithful(markdown, baseline) is True


def test_unfaithful_markdown_loses_content():
    """Le Markdown a perdu la majorité du contenu → rejeté (repli texte plat)."""
    baseline = "mot " * 300   # ~900 car. alphanum.
    markdown = "mot " * 50    # ~150 car. alphanum. < 80 %
    assert _is_faithful(markdown, baseline) is False


def test_short_baseline_not_judged():
    """Référence trop courte (ex. PDF scanné) → on ne bloque pas sur la fidélité."""
    assert _is_faithful("", "trop court") is True
