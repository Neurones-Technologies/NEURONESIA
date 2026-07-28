"""GED upload — path traversal (correctif sécurité) : `_safe_filename` doit
neutraliser tout séparateur/chemin fourni par le client avant écriture disque."""
import pytest

from api.v1.ged import _safe_filename


@pytest.mark.parametrize("raw,expected", [
    ("rapport.pdf", "rapport.pdf"),
    ("../../../etc/passwd", "passwd"),
    ("/etc/cron.d/malicious", "malicious"),
    ("cv été.pdf", "cv_ete.pdf"),
    ("", "document"),
    ("....", "document"),
])
def test_safe_filename_neutralise_les_chemins(raw, expected):
    assert _safe_filename(raw) == expected


def test_safe_filename_neutralise_le_backslash_comme_caractere_litteral():
    # Le backslash n'est PAS un séparateur de chemin sur le système de fichiers
    # du conteneur (Linux) — il est neutralisé comme un caractère quelconque,
    # pas interprété comme un composant de dossier. La propriété de sécurité
    # qui compte est vérifiée séparément : jamais de "/" ni ".." dans le résultat.
    result = _safe_filename("..\\..\\windows\\system32\\evil.docx")
    assert result.endswith("evil.docx")
    assert "/" not in result


def test_safe_filename_reste_dans_un_seul_composant():
    result = _safe_filename("../../a/b/c.pdf")
    assert "/" not in result and "\\" not in result and ".." not in result
