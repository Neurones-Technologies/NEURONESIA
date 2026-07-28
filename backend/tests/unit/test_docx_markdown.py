"""Tests du rendu Markdown DOCX (POC parsing GED) — fonctions pures."""
import pytest

from adapters.parser.docx_markdown import (
    heading_level,
    is_bullet_style,
    md_cell,
    grid_to_markdown,
    strip_control,
)


@pytest.mark.parametrize("style, level", [
    ("Heading 1", 1),
    ("Heading 3", 3),
    ("Titre 2", 2),       # français
    ("Title", 1),
    ("Titre", 1),
    ("Heading 9", 6),     # plafonné à 6
    ("Normal", 0),
    ("", 0),
    (None, 0),
])
def test_heading_level(style, level):
    assert heading_level(style) == level


@pytest.mark.parametrize("style, expected", [
    ("List Bullet", True),
    ("Liste à puces", True),
    ("List Paragraph", False),
    ("Normal", False),
    ("", False),
])
def test_is_bullet_style(style, expected):
    assert is_bullet_style(style) is expected


@pytest.mark.parametrize("raw, expected", [
    ("x\ny", "x y"),
    ("a|b", "a\\|b"),
    ("  espacé  ", "espacé"),
    (None, ""),
])
def test_md_cell(raw, expected):
    assert md_cell(raw) == expected


def test_grid_to_markdown_basic():
    grid = [["Désignation", "Qté"], ["Routeur", "4"]]
    md = grid_to_markdown(grid)
    assert md == (
        "| Désignation | Qté |\n"
        "| --- | --- |\n"
        "| Routeur | 4 |"
    )


def test_grid_to_markdown_ragged_rows_are_padded():
    grid = [["A", "B", "C"], ["1"]]
    lines = grid_to_markdown(grid).splitlines()
    assert lines[0] == "| A | B | C |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| 1 |  |  |"


def test_grid_to_markdown_empty():
    assert grid_to_markdown([]) == ""


def test_strip_control_removes_nonprintable_keeps_newline():
    assert strip_control("a\x00b\nc") == "ab\nc"
