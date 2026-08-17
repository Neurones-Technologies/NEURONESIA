"""Tests de l'exclusion des partenaires intra-groupe du miroir Odoo.

Le risque protégé ici n'est pas « le filtre ne marche pas » mais son inverse :
qu'il morde TROP. La base compte dix entités « NEURONES » distinctes
(NEURONES TECHNOLOGIES, BENIN, ACADEMY, GROUP, DISTRIBUTIONS, GUINEE, SA…) et
une implémentation par `LIKE '%NEURONES%'` — la tentation évidente, déjà
présente ailleurs dans le code — les ferait toutes disparaître du cockpit.

Seule NEURONES TECHNOLOGIES BF doit sortir, par ses deux IDs Odoo (client 2671,
fournisseur 3485). Les tests de non-exclusion ci-dessous sont donc les plus
importants du fichier.
"""
import pytest

from config.settings import settings
from jobs.odoo_sync_job import _est_exclu


# ── Le filtre de synchronisation ────────────────────────────────────────────

@pytest.mark.parametrize("odoo_id", [2671, "2671", 3485, "3485"])
def test_exclut_les_deux_fiches_bf(odoo_id):
    """BF porte deux fiches Odoo ; l'ID arrive tantôt en int, tantôt en str."""
    assert _est_exclu(odoo_id) is True


def test_exclut_par_nom_exact_insensible_a_la_casse():
    """Les `dossiers` n'ont pas de client_id : seul le nom permet de trancher."""
    assert _est_exclu(None, "NEURONES TECHNOLOGIES BF") is True
    assert _est_exclu(None, "neurones technologies bf") is True
    assert _est_exclu(None, "  NEURONES TECHNOLOGIES BF  ") is True


@pytest.mark.parametrize("odoo_id,nom", [
    (1,    "NEURONES TECHNOLOGIES"),
    (532,  "NEURONES TECHNOLOGIES BENIN"),
    (3866, "NEURONES ACADEMY"),
    (1026, "NEURONES GROUP"),
    (1027, "NEURONES DISTRIBUTIONS"),
    (3826, "NEURONES TECHNOLOGIES GUINEE SARLU. "),
    (4757, "NEURONES TECHNOLOGIES SA"),
])
def test_n_exclut_pas_les_autres_entites_du_groupe(odoo_id, nom):
    """Le garde-fou du fichier : une dérive vers LIKE '%NEURONES%' casse ici."""
    assert _est_exclu(odoo_id, nom) is False


def test_partenaire_absent_jamais_exclu():
    """client_id vide ou non numérique (BDC sans partenaire) : pas d'exclusion."""
    assert _est_exclu(None, "") is False
    assert _est_exclu("", "") is False
    assert _est_exclu("pas-un-id", "") is False


def test_client_tiers_ordinaire_non_exclu():
    assert _est_exclu(9999, "ECOBANK COTE D'IVOIRE") is False


def test_ids_exclus_configures():
    """Les IDs viennent de la config, jamais du code appelant."""
    assert settings.excluded_partner_odoo_ids == {2671, 3485}


# ── La purge du miroir ──────────────────────────────────────────────────────

_SCHEMA = [
    "CREATE TABLE clients (client_id TEXT PRIMARY KEY, name TEXT)",
    "CREATE TABLE suppliers (supplier_id TEXT PRIMARY KEY, name TEXT)",
    "CREATE TABLE sale_orders (order_id TEXT PRIMARY KEY, client_id TEXT, client_name TEXT)",
    "CREATE TABLE invoices (invoice_id TEXT PRIMARY KEY, client_id TEXT)",
    "CREATE TABLE dossiers (dossier_ref TEXT PRIMARY KEY, client_name TEXT)",
]

_SEED = [
    # L'entité à purger, sous ses deux fiches.
    ("INSERT INTO clients VALUES ('2671', 'NEURONES TECHNOLOGIES BF')", ()),
    ("INSERT INTO suppliers VALUES ('3485', 'NEURONES TECHNOLOGIES BF')", ()),
    ("INSERT INTO sale_orders VALUES ('so_1', '2671', 'NEURONES TECHNOLOGIES BF')", ()),
    ("INSERT INTO invoices VALUES ('inv_1', '2671')", ()),
    ("INSERT INTO dossiers VALUES ('DC/2021/0117', 'NEURONES TECHNOLOGIES BF')", ()),
    # Entités du groupe à PRÉSERVER.
    ("INSERT INTO clients VALUES ('1', 'NEURONES TECHNOLOGIES')", ()),
    ("INSERT INTO clients VALUES ('532', 'NEURONES TECHNOLOGIES BENIN')", ()),
    ("INSERT INTO clients VALUES ('3866', 'NEURONES ACADEMY')", ()),
    ("INSERT INTO sale_orders VALUES ('so_2', '1', 'NEURONES TECHNOLOGIES')", ()),
    ("INSERT INTO dossiers VALUES ('DC/2021/0500', 'NEURONES ACADEMY')", ()),
    # Client tiers.
    ("INSERT INTO clients VALUES ('9999', 'ECOBANK')", ()),
    ("INSERT INTO sale_orders VALUES ('so_3', '9999', 'ECOBANK')", ()),
]


@pytest.fixture
def miroir(tmp_path):
    """Miroir SQLite jetable reproduisant la cohabitation des entités NEURONES."""
    import sqlite3
    db = tmp_path / "miroir.db"
    conn = sqlite3.connect(db)
    for ddl in _SCHEMA:
        conn.execute(ddl)
    for sql, params in _SEED:
        conn.execute(sql, params)
    conn.commit()
    conn.close()
    return db


def _purger_sync(db, ids, noms):
    """Rejoue la logique de purge du script sur une base de test synchrone.

    Le script réel est asynchrone et lié à AsyncSessionLocal ; on en reproduit
    ici les clauses SQL — ce sont elles que le test doit protéger.
    """
    import sqlite3
    conn = sqlite3.connect(db)
    marques_ids = ",".join("?" * len(ids))
    marques_noms = ",".join("?" * len(noms))
    supprimees = 0
    for table, clause, params in [
        ("invoices",    f"client_id IN ({marques_ids})", ids),
        ("sale_orders", f"client_id IN ({marques_ids})", ids),
        ("dossiers",    f"UPPER(TRIM(client_name)) IN ({marques_noms})", noms),
        ("clients",     f"client_id IN ({marques_ids})", ids),
        ("suppliers",   f"supplier_id IN ({marques_ids})", ids),
    ]:
        cur = conn.execute(f"DELETE FROM {table} WHERE {clause}", params)
        supprimees += cur.rowcount
    conn.commit()
    conn.close()
    return supprimees


def _compter(db, sql):
    import sqlite3
    conn = sqlite3.connect(db)
    n = conn.execute(sql).fetchone()[0]
    conn.close()
    return n


def test_purge_supprime_toute_trace_de_bf(miroir):
    ids = ["2671", "3485"]
    noms = ["NEURONES TECHNOLOGIES BF"]
    assert _purger_sync(miroir, ids, noms) == 5

    assert _compter(miroir, "SELECT COUNT(*) FROM clients WHERE client_id='2671'") == 0
    assert _compter(miroir, "SELECT COUNT(*) FROM suppliers WHERE supplier_id='3485'") == 0
    assert _compter(miroir, "SELECT COUNT(*) FROM sale_orders WHERE client_id='2671'") == 0
    assert _compter(miroir, "SELECT COUNT(*) FROM invoices WHERE client_id='2671'") == 0
    assert _compter(
        miroir,
        "SELECT COUNT(*) FROM dossiers WHERE client_name='NEURONES TECHNOLOGIES BF'"
    ) == 0


def test_purge_preserve_les_autres_entites_neurones(miroir):
    """Le test qui distingue une exclusion chirurgicale d'un LIKE destructeur."""
    _purger_sync(miroir, ["2671", "3485"], ["NEURONES TECHNOLOGIES BF"])

    assert _compter(miroir, "SELECT COUNT(*) FROM clients WHERE name LIKE '%NEURONES%'") == 3
    assert _compter(miroir, "SELECT COUNT(*) FROM sale_orders WHERE client_id='1'") == 1
    assert _compter(
        miroir, "SELECT COUNT(*) FROM dossiers WHERE client_name='NEURONES ACADEMY'"
    ) == 1
    # Et le client tiers est évidemment intact.
    assert _compter(miroir, "SELECT COUNT(*) FROM clients WHERE client_id='9999'") == 1


def test_purge_idempotente(miroir):
    """Un second passage ne supprime rien et ne lève pas d'erreur."""
    ids, noms = ["2671", "3485"], ["NEURONES TECHNOLOGIES BF"]
    assert _purger_sync(miroir, ids, noms) == 5
    assert _purger_sync(miroir, ids, noms) == 0
