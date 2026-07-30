"""LocalCRMAdapter.get_client_portfolio — agrégat portefeuille et son
enrichissement.

L'enrichissement (fiche client, dernier projet, dernier commercial) se faisait
en trois requêtes PAR client, soit 600 allers-retours SQLite en série à
`limit=200`. Il se fait maintenant en trois requêtes pour tout le lot. Ces tests
verrouillent ce qui pourrait silencieusement changer au passage : le dernier
projet et le dernier commercial doivent rester ceux du dossier le plus récent
QUI LES RENSEIGNE, chacun indépendamment de l'autre — le dossier le plus récent
peut porter l'un sans l'autre, et une fenêtre unique les confondrait.

Vraie base SQLite temporaire (même approche que test_supplier_intelligence) : la
logique est en SQL brut, avec des fonctions de fenêtrage plus fiables à vérifier
bout en bout qu'à mocker requête par requête.
"""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import adapters.crm.local_crm_adapter as local_crm_adapter
from adapters.crm.local_crm_adapter import LocalCRMAdapter
from db.database import Base
from db.models import ClientModel, DossierModel


@pytest.fixture
def db_session_factory(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    monkeypatch.setattr(local_crm_adapter, "AsyncSessionLocal", session_factory)
    return session_factory


def _dossier(ref, client, *, jour, ca=0.0, reste=0.0, backlog=0.0, projet=None, commercial=None):
    return DossierModel(
        dossier_ref=ref,
        odoo_id=abs(hash(ref)) % 100000,
        client_name=client,
        project_name=projet,
        salesperson=commercial,
        date_creation=datetime(2026, 1, jour),
        ca_definitif=ca,
        reste_a_encaisser=reste,
        backlog=backlog,
    )


def _seed(session_factory, objets):
    async def _run():
        async with session_factory() as session:
            for o in objets:
                session.add(o)
            await session.commit()

    asyncio.run(_run())


def _portfolio(**kwargs):
    return asyncio.run(LocalCRMAdapter().get_client_portfolio(**kwargs))


def test_agregats_et_enrichissement_par_lot(db_session_factory):
    """Les agrégats et l'enrichissement d'un lot de clients sont corrects."""
    _seed(db_session_factory, [
        ClientModel(client_id="1", name="ALPHA SA", sector="Banque",
                    contact_email="c@alpha.ci", phone="+225 01"),
        ClientModel(client_id="2", name="BETA SARL", sector="Télécom",
                    contact_email="c@beta.ci", phone="+225 02"),
        _dossier("D1", "ALPHA SA", jour=1, ca=10_000_000, reste=3_000_000, backlog=1_000_000,
                 projet="Socle réseau", commercial="Awa"),
        _dossier("D2", "ALPHA SA", jour=5, ca=5_000_000, reste=2_000_000, backlog=500_000,
                 projet="Extension WAN", commercial="Bakary"),
        _dossier("D3", "BETA SARL", jour=3, ca=1_000_000, reste=0, backlog=0,
                 projet="Firewall", commercial="Cissé"),
    ])

    par_client = {c["client"]: c for c in _portfolio(limit=50)}

    alpha = par_client["ALPHA SA"]
    assert alpha["nb_dossiers"] == 2
    assert alpha["ca_total_xof"] == 15_000_000
    assert alpha["reste_a_encaisser_xof"] == 5_000_000
    assert alpha["backlog_xof"] == 1_500_000
    assert alpha["premiere_commande"] == "2026-01-01"
    assert alpha["derniere_commande"] == "2026-01-05"
    # Enrichissement rattaché au BON client, pas décalé d'une ligne
    assert (alpha["secteur"], alpha["contact_email"], alpha["telephone"]) == (
        "Banque", "c@alpha.ci", "+225 01")
    # Dossier le plus récent (D2, le 5) et non le premier inséré
    assert alpha["dernier_projet"] == "Extension WAN"
    assert alpha["salesperson"] == "Bakary"

    beta = par_client["BETA SARL"]
    assert beta["secteur"] == "Télécom"
    assert beta["dernier_projet"] == "Firewall"
    assert beta["salesperson"] == "Cissé"

    # Tri par CA décroissant conservé
    assert [c["client"] for c in _portfolio(limit=50)] == ["ALPHA SA", "BETA SARL"]


def test_dernier_projet_et_dernier_commercial_sont_independants(db_session_factory):
    """Le dossier le plus récent peut renseigner l'un sans l'autre : chacun est
    pris sur le dernier dossier qui le porte, et non sur une même ligne."""
    _seed(db_session_factory, [
        _dossier("D1", "GAMMA", jour=1, ca=9_000_000, projet="Ancien projet", commercial="Awa"),
        # Le plus récent porte un projet mais aucun commercial…
        _dossier("D2", "GAMMA", jour=9, ca=1_000_000, projet="Projet récent", commercial=None),
        # …et celui du milieu, un commercial mais aucun projet.
        _dossier("D3", "GAMMA", jour=5, ca=1_000_000, projet="", commercial="Bakary"),
    ])

    gamma = _portfolio(limit=50)[0]
    assert gamma["dernier_projet"] == "Projet récent"   # D2, le plus récent avec un projet
    assert gamma["salesperson"] == "Bakary"             # D3, le plus récent avec un commercial


def test_client_sans_fiche_ni_projet_reste_expose(db_session_factory):
    """Un client présent dans `dossiers` mais absent de `clients` garde sa ligne,
    avec un enrichissement à None — jamais d'exclusion silencieuse."""
    _seed(db_session_factory, [
        _dossier("D1", "DELTA", jour=2, ca=4_000_000, projet=None, commercial=None),
    ])

    delta = _portfolio(limit=50)[0]
    assert delta["client"] == "DELTA"
    assert delta["ca_total_xof"] == 4_000_000
    assert (delta["secteur"], delta["contact_email"], delta["telephone"]) == (None, None, None)
    assert (delta["dernier_projet"], delta["salesperson"]) == (None, None)


def test_filtre_clients_ignore_le_classement_par_ca(db_session_factory):
    """`clients=[...]` sert les comptes demandés même hors du top CA — c'est le
    besoin de la file d'arbitrage, dont les débiteurs ne sont pas les plus gros
    clients et disparaissaient donc du portefeuille servi (sans commercial de
    compte ni backlog dans le dossier affiché)."""
    _seed(db_session_factory, [
        ClientModel(client_id="9", name="PETIT COMPTE", sector="Public"),
        _dossier("D1", "GROS COMPTE", jour=1, ca=900_000_000),
        _dossier("D2", "MOYEN COMPTE", jour=1, ca=50_000_000),
        _dossier("D3", "PETIT COMPTE", jour=1, ca=1_000_000, backlog=7_000,
                 commercial="Awa"),
    ])

    # Le top 2 par CA ne contient pas PETIT COMPTE…
    assert "PETIT COMPTE" not in {c["client"] for c in _portfolio(limit=2)}
    # …mais le demander nommément le sert, avec son enrichissement.
    demande = _portfolio(clients=["PETIT COMPTE"])
    assert [c["client"] for c in demande] == ["PETIT COMPTE"]
    assert demande[0]["salesperson"] == "Awa"
    assert demande[0]["backlog_xof"] == 7_000
    assert demande[0]["secteur"] == "Public"

    # `limit` ne tronque pas une liste explicitement nommée.
    noms = ["GROS COMPTE", "MOYEN COMPTE", "PETIT COMPTE"]
    assert {c["client"] for c in _portfolio(limit=1, clients=noms)} == set(noms)

    # Un nom inconnu ne fabrique pas de ligne vide ; une liste vide ne renvoie rien.
    assert _portfolio(clients=["CLIENT INEXISTANT"]) == []
    assert _portfolio(clients=[]) == []


def test_aucun_dossier_ne_leve_pas(db_session_factory):
    """Base sans dossier : liste vide, pas d'exception sur l'étape d'enrichissement."""
    _seed(db_session_factory, [ClientModel(client_id="1", name="ALPHA SA")])
    assert _portfolio(limit=50) == []
