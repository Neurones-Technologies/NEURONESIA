"""Garde-fou text-to-SQL — vecteurs red-team (Phase 3)."""
import pytest

from core.services.sql_guard import SqlGuardError, validate_select
from core.services.sql_schema import KB_TABLES, ODOO_TABLES


def test_select_valide_ajoute_limit():
    out = validate_select("SELECT doc_id, fichier_source FROM kb_attestation", KB_TABLES)
    assert out.endswith("LIMIT 200")


def test_with_cte_autorise():
    sql = "WITH x AS (SELECT montant_valeur FROM kb_attestation) SELECT * FROM x"
    assert validate_select(sql, KB_TABLES | {"x"})  # x = CTE, déclarée dans allowed pour le test


def test_limit_clampe():
    out = validate_select("SELECT doc_id FROM kb_cv LIMIT 9999", KB_TABLES)
    assert "LIMIT 200" in out and "9999" not in out


@pytest.mark.parametrize("sql", [
    "UPDATE kb_cv SET nom_complet='x'",
    "DELETE FROM kb_cv",
    "INSERT INTO kb_cv(doc_id) VALUES ('x')",
    "DROP TABLE kb_cv",
    "ALTER TABLE kb_cv ADD COLUMN z TEXT",
    "CREATE TABLE evil(x)",
    "SELECT * FROM kb_cv; DROP TABLE kb_cv",          # multi-statement
    "ATTACH DATABASE 'x.db' AS y",
    "SELECT load_extension('x')",
    "PRAGMA query_only=OFF",
    "SELECT * FROM kb_cv -- commentaire",             # commentaire ligne
    "SELECT * FROM kb_cv /* bloc */",                  # commentaire bloc
    "SELECT name FROM sqlite_master",                  # pseudo-table système
])
def test_requetes_dangereuses_rejetees(sql):
    with pytest.raises(SqlGuardError):
        validate_select(sql, KB_TABLES)


def test_doit_commencer_par_select_ou_with():
    with pytest.raises(SqlGuardError):
        validate_select("EXPLAIN SELECT * FROM kb_cv", KB_TABLES)


def test_table_hors_whitelist_rejetee():
    # users / token_usage NE sont PAS dans la liste blanche → fuite bloquée.
    with pytest.raises(SqlGuardError):
        validate_select("SELECT email, hashed_password FROM users", KB_TABLES)
    with pytest.raises(SqlGuardError):
        validate_select("SELECT * FROM token_usage", ODOO_TABLES)


def test_join_vers_table_interdite_rejetee():
    with pytest.raises(SqlGuardError):
        validate_select(
            "SELECT c.nom_complet FROM kb_cv c JOIN users u ON u.id=c.doc_id", KB_TABLES)


def test_json_each_nest_pas_traite_comme_table():
    # json_each est une fonction table-valued, pas une table à filtrer.
    sql = ("SELECT o.client_name FROM sale_orders o, json_each(o.order_lines) j "
           "WHERE json_extract(j.value,'$.product') LIKE '%Azure%'")
    assert validate_select(sql, ODOO_TABLES)


def test_trop_de_jointures_rejete():
    joins = " ".join(f"JOIN kb_cv t{i} ON t{i}.doc_id=kb_cv.doc_id" for i in range(9))
    with pytest.raises(SqlGuardError):
        validate_select(f"SELECT * FROM kb_cv {joins}", KB_TABLES)


def test_requete_trop_longue_rejetee():
    with pytest.raises(SqlGuardError):
        validate_select("SELECT doc_id FROM kb_cv WHERE " + "x=1 AND " * 1000, KB_TABLES)
