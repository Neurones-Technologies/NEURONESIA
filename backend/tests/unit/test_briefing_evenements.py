"""Détection d'événements et hygiène du pipe.

Deux pièges gouvernent ces tests :
  - annoncer « aucun mouvement » là où il n'y a en réalité aucun MOYEN de
    mesurer (moins de deux snapshots pour différencier les étapes) ;
  - remonter « ce qui dort » en un seul tas, où les 3 015 opportunités périmées
    noient les 108 affaires réellement récupérables.
"""
import asyncio
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base
from db.models import (
    InvoiceModel, OpportunityModel, PipelineSnapshotModel, PurchaseOrderModel, SaleOrderModel,
)
from modules.uc_briefing import evenements

AUJOURD_HUI = date(2026, 8, 27)


def _dt(jour: date):
    return datetime(jour.year, jour.month, jour.day)


async def _dans_la_base(corps, semer):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all(semer())
        await session.commit()

    import db.database as database
    originaux = (database.AsyncSessionLocal, evenements.AsyncSessionLocal)
    database.AsyncSessionLocal = factory
    evenements.AsyncSessionLocal = factory
    try:
        return await corps()
    finally:
        database.AsyncSessionLocal, evenements.AsyncSessionLocal = originaux
        await engine.dispose()


def _mouvements_semences():
    return [
        SaleOrderModel(order_id="so1", client_id="1", client_name="CIE", name="FP/1",
                       amount=300.0, state="sale", date_order=_dt(date(2026, 8, 21))),
        # Hors fenêtre : une borne mal posée le ferait entrer.
        SaleOrderModel(order_id="so2", client_id="1", client_name="CIE", name="FP/2",
                       amount=999.0, state="sale", date_order=_dt(date(2026, 8, 19))),
        InvoiceModel(invoice_id="i1", client_id="1", amount=80.0, amount_residual=80.0,
                     status="pending", invoice_date=_dt(date(2026, 8, 22)),
                     due_date=_dt(date(2026, 9, 22))),
        InvoiceModel(invoice_id="i2", client_id="1", amount=50.0, amount_residual=0.0,
                     status="paid", invoice_date=_dt(date(2026, 1, 5)),
                     due_date=_dt(date(2026, 2, 5)), payment_date=_dt(date(2026, 8, 23))),
        PurchaseOrderModel(order_id="po1", client_id="9", client_name="WESTCON", name="PO/1",
                           amount=120.0, state="purchase", date_order=_dt(date(2026, 8, 24))),
        OpportunityModel(opp_id="o1", client_id="1", client_name="CIE", name="Refresh",
                         stage="4-Négociation", expected_revenue=1000.0, probability=50.0,
                         write_date=_dt(date(2026, 8, 25))),
    ]


def test_mouvements_ne_retiennent_que_la_fenetre():
    async def corps():
        return await evenements.mouvements(date(2026, 8, 20), AUJOURD_HUI)
    m = asyncio.run(_dans_la_base(corps, _mouvements_semences))

    assert m["commandes_entrees"]["nb"] == 1
    assert m["commandes_entrees"]["montant_xof"] == 300.0
    assert m["factures_emises"]["nb"] == 1
    assert m["factures_reglees"]["nb"] == 1
    assert m["achats_engages"]["nb"] == 1
    assert m["opportunites_retouchees"]["nb"] == 1
    assert m["total_evenements"] == 5


def test_total_evenements_couvre_toutes_les_categories_rendues():
    """Une catégorie comptée mais jamais rendue produit une puce vide : le
    compteur et les catégories publiées doivent rester alignés."""
    async def corps():
        return await evenements.mouvements(date(2026, 8, 20), AUJOURD_HUI)
    m = asyncio.run(_dans_la_base(corps, _mouvements_semences))
    somme = sum(m[cle]["nb"] for cle in
                ("commandes_entrees", "factures_emises", "factures_reglees",
                 "achats_engages", "opportunites_retouchees"))
    assert m["total_evenements"] == somme


def test_changements_etape_non_mesurables_le_disent():
    """Sans deux snapshots encadrants, l'absence de mouvement détecté n'est pas
    une absence de mouvement — et la puce ne doit pas prétendre l'inverse."""
    async def corps():
        return await evenements.changements_etape(date(2026, 8, 20), AUJOURD_HUI)
    res = asyncio.run(_dans_la_base(corps, _mouvements_semences))
    assert res["mesurable"] is False
    assert res["raison"]


def test_changements_etape_par_difference_de_snapshots():
    def semer():
        commun = dict(opp_id="o1", client_name="CIE", name="Refresh",
                      expected_revenue=1000.0, probability=50.0)
        return [
            PipelineSnapshotModel(snapshot_date=date(2026, 8, 18), stage="1-Qualification", **commun),
            PipelineSnapshotModel(snapshot_date=date(2026, 8, 25), stage="4-Négociation", **commun),
            # Entrée au pipe : présente au second snapshot, absente au premier.
            PipelineSnapshotModel(snapshot_date=date(2026, 8, 25), opp_id="o2",
                                  client_name="SGCI", name="Neuve", stage="1-Qualification",
                                  expected_revenue=400.0, probability=10.0),
        ]

    async def corps():
        return await evenements.changements_etape(date(2026, 8, 20), AUJOURD_HUI)
    res = asyncio.run(_dans_la_base(corps, semer))

    assert res["mesurable"] is True
    assert res["nb"] == 1
    assert res["top"][0]["de"] == "1-Qualification"
    assert res["top"][0]["vers"] == "4-Négociation"
    assert res["nb_entrees_pipe"] == 1


def _pipe_semences():
    return [
        # Encore dans les temps, sans retouche depuis longtemps → à relancer.
        OpportunityModel(opp_id="a", client_id="1", client_name="MOOV", name="Refresh WAN",
                         stage="2-Montage", expected_revenue=900.0, probability=40.0,
                         deadline=_dt(date(2026, 12, 31)), write_date=_dt(date(2026, 4, 1))),
        # Encore dans les temps et retouchée hier → ni l'un ni l'autre.
        OpportunityModel(opp_id="b", client_id="1", client_name="CIE", name="Active",
                         stage="2-Montage", expected_revenue=700.0, probability=40.0,
                         deadline=_dt(date(2026, 12, 31)), write_date=_dt(date(2026, 8, 26))),
        # Échéance dépassée, stade ouvert → à assainir.
        OpportunityModel(opp_id="c", client_id="2", client_name="SGCI", name="Périmée",
                         stage="3-Transmise", expected_revenue=5000.0, probability=30.0,
                         deadline=_dt(date(2025, 1, 1)), write_date=_dt(date(2025, 1, 1))),
        # Fermée : hors de tout tas, quel que soit son âge.
        OpportunityModel(opp_id="d", client_id="2", client_name="SGCI", name="Gagnée",
                         stage="6-Gagné", expected_revenue=8000.0, probability=100.0,
                         deadline=_dt(date(2025, 1, 1)), write_date=_dt(date(2025, 1, 1))),
        # Sans échéance : un troisième cas, qui ne doit contaminer aucun des deux.
        OpportunityModel(opp_id="e", client_id="2", client_name="BAD", name="Sans date",
                         stage="1-Qualification", expected_revenue=200.0, probability=10.0,
                         write_date=_dt(date(2025, 1, 1))),
    ]


def test_hygiene_pipe_separe_le_recuperable_du_perime():
    """Un seul tas remonterait 3 015 lignes triées par montant, donc dominé par
    les plus périmées : une liste que personne ne peut traiter."""
    async def corps():
        return await evenements.hygiene_pipe(seuil_jours=15, as_of=AUJOURD_HUI)
    h = asyncio.run(_dans_la_base(corps, _pipe_semences))

    assert h["a_relancer"]["nb"] == 1
    assert h["a_relancer"]["montant_xof"] == 900.0
    assert h["a_relancer"]["top"][0]["client"] == "MOOV"
    assert h["a_assainir"]["nb"] == 1          # la gagnée est exclue
    assert h["a_assainir"]["montant_xof"] == 5000.0
    assert h["sans_echeance"]["nb"] == 1


def test_hygiene_pipe_suit_le_seuil():
    """Le seuil de dormance est réglable par rôle : le déplacer déplace le tas."""
    async def corps():
        return (
            await evenements.hygiene_pipe(seuil_jours=15, as_of=AUJOURD_HUI),
            await evenements.hygiene_pipe(seuil_jours=365, as_of=AUJOURD_HUI),
        )
    court, long = asyncio.run(_dans_la_base(corps, _pipe_semences))
    assert court["a_relancer"]["nb"] == 1
    assert long["a_relancer"]["nb"] == 0       # 148 j de silence < 365 j
