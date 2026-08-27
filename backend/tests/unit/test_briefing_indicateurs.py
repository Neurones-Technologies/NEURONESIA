"""Moteur de delta du briefing — historisation, reconstitution, comparaison.

Les tests portent sur ce qui casse EN SILENCE. Un moteur de delta se trompe
sans jamais lever : il affiche un zéro là où il faudrait se taire, compare deux
dates qui ne se comparent pas, ou date « vs hier » un point vieux de deux
semaines. Aucune de ces erreurs ne produit d'exception, et toutes produisent un
chiffre faux avec l'autorité du calcul automatique.
"""
import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base
from db.models import (
    BacklogSnapshotModel, DossierModel, InvoiceModel, OpportunityModel,
    PipelineSnapshotModel, SaleOrderModel,
)
from modules.uc_briefing import indicateurs

AUJOURD_HUI = date(2026, 8, 27)


async def _base():
    """Base en mémoire, câblée à la place de la vraie le temps du test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _dt(jour: date):
    from datetime import datetime
    return datetime(jour.year, jour.month, jour.day)


async def _semer(factory):
    async with factory() as session:
        session.add_all([
            # Trois commandes étalées : le cumul du 10/08 doit valoir 300, celui
            # du 20/08 500, et celui du 27/08 500 — c'est ce que la
            # reconstitution doit retrouver sans qu'aucun snapshot n'ait été pris.
            SaleOrderModel(order_id="so1", client_id="1", client_name="CIE", name="FP/1",
                           amount=100.0, state="sale", date_order=_dt(date(2026, 3, 1))),
            SaleOrderModel(order_id="so2", client_id="1", client_name="CIE", name="FP/2",
                           amount=200.0, state="sale", date_order=_dt(date(2026, 8, 10))),
            SaleOrderModel(order_id="so3", client_id="2", client_name="SGCI", name="FP/3",
                           amount=200.0, state="sale", date_order=_dt(date(2026, 8, 20))),
            # Commande de l'exercice précédent : elle ne doit JAMAIS entrer dans
            # un cumul 2026, et c'est elle qui rend la remise à zéro observable.
            SaleOrderModel(order_id="so0", client_id="1", client_name="CIE", name="FP/0",
                           amount=9999.0, state="sale", date_order=_dt(date(2025, 12, 31))),
            # Facture échue jamais réglée, et facture réglée le 15/08 : au 10/08
            # les deux pesaient, au 27/08 une seule.
            InvoiceModel(invoice_id="i1", client_id="1", amount=500.0, amount_residual=500.0,
                         status="pending", invoice_date=_dt(date(2026, 1, 5)),
                         due_date=_dt(date(2026, 2, 5))),
            InvoiceModel(invoice_id="i2", client_id="1", amount=300.0, amount_residual=0.0,
                         status="paid", invoice_date=_dt(date(2026, 1, 5)),
                         due_date=_dt(date(2026, 2, 5)), payment_date=_dt(date(2026, 8, 15))),
            OpportunityModel(opp_id="o1", client_id="1", client_name="CIE", name="Refresh",
                             stage="4-Négociation", expected_revenue=1000.0, probability=50.0,
                             deadline=_dt(date(2026, 12, 31))),
            OpportunityModel(opp_id="o2", client_id="2", client_name="SGCI", name="TMA",
                             stage="6-Gagné", expected_revenue=5000.0, probability=100.0,
                             deadline=_dt(date(2026, 12, 31))),
            OpportunityModel(opp_id="o3", client_id="2", client_name="SGCI", name="Périmée",
                             stage="2-Montage", expected_revenue=800.0, probability=40.0,
                             deadline=_dt(date(2026, 1, 1))),
            DossierModel(dossier_ref="DC/1", odoo_id=1, client_name="CIE",
                         backlog=700.0, reste_a_encaisser=400.0),
        ])
        await session.commit()


async def _snapshot_pipe(factory, jour: date, revenu: float, echeance: date):
    async with factory() as session:
        session.add(PipelineSnapshotModel(
            snapshot_date=jour, opp_id="o1", client_name="CIE", name="Refresh",
            stage="4-Négociation", expected_revenue=revenu, probability=50.0,
            deadline=_dt(echeance),
        ))
        session.add(BacklogSnapshotModel(
            snapshot_date=jour, dossier_ref="DC/1", client_name="CIE", backlog=revenu / 2,
        ))
        await session.commit()


async def _dans_la_base(corps, snapshots=()):
    engine, factory = await _base()
    await _semer(factory)
    for jour, revenu, echeance in snapshots:
        await _snapshot_pipe(factory, jour, revenu, echeance)

    import db.database as database
    originaux = (database.AsyncSessionLocal, indicateurs.AsyncSessionLocal)
    database.AsyncSessionLocal = factory
    indicateurs.AsyncSessionLocal = factory
    indicateurs.vider_cache_snapshots()
    try:
        return await corps(factory)
    finally:
        database.AsyncSessionLocal, indicateurs.AsyncSessionLocal = originaux
        indicateurs.vider_cache_snapshots()
        await engine.dispose()


# ── Reconstitution des flux ──────────────────────────────────────────────────

def test_flux_se_reconstitue_sans_aucun_snapshot():
    """L'apport central du module : le CA commandé du 10 août est calculable
    aujourd'hui, parce que `date_order` porte la date. Sans cette propriété, le
    delta ne serait disponible qu'après trente nuits d'historisation."""
    async def corps(_):
        return [
            await indicateurs.calculer("ca_commande_ytd", j, historique=True)
            for j in (date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 20), AUJOURD_HUI)
        ]
    veille, dix, vingt, aujourd_hui = asyncio.run(_dans_la_base(corps))
    assert (veille, dix, vingt, aujourd_hui) == (100.0, 300.0, 500.0, 500.0)


def test_flux_ne_franchit_pas_l_exercice():
    """La commande du 31/12/2025 ne doit jamais entrer dans un cumul 2026."""
    async def corps(_):
        return await indicateurs.calculer("ca_commande_ytd", date(2026, 1, 2), historique=True)
    assert asyncio.run(_dans_la_base(corps)) == 0.0


def test_impayes_se_reconstituent_par_les_dates_de_reglement():
    """Une facture réglée le 15/08 pesait son montant plein jusque-là, et rien
    ensuite — c'est ce qui rend l'encours d'un jour passé calculable."""
    async def corps(_):
        return (
            await indicateurs.calculer("impayes_echus", date(2026, 8, 10), historique=True),
            await indicateurs.calculer("impayes_echus", AUJOURD_HUI, historique=True),
        )
    avant, apres = asyncio.run(_dans_la_base(corps))
    assert avant == 800.0     # les deux factures étaient dues
    assert apres == 500.0     # une seule reste ouverte


# ── Le garde-fou central : jamais un zéro pour un stock non capturé ──────────

def test_stock_sans_snapshot_rend_none_et_non_zero():
    """LE défaut que ce module existe pour rendre impossible.

    La requête historique d'un stock est un `SUM ... WHERE snapshot_date = :d` :
    une journée jamais capturée rend tranquillement 0. Ce zéro se lit comme un
    backlog effondré, et le delta du lendemain comme une remontée intégrale.
    """
    async def corps(_):
        return {
            cle: await indicateurs.calculer(cle, date(2026, 6, 12), historique=True)
            for cle in ("pipe_brut", "pipe_actif_brut", "backlog", "reste_a_encaisser")
        }
    valeurs = asyncio.run(_dans_la_base(corps))
    assert set(valeurs.values()) == {None}


def test_stock_avec_snapshot_est_mesurable():
    async def corps(_):
        return await indicateurs.calculer("pipe_brut", date(2026, 8, 13), historique=True)
    valeur = asyncio.run(_dans_la_base(
        corps, snapshots=[(date(2026, 8, 13), 1000.0, date(2026, 12, 31))]
    ))
    assert valeur == 1000.0


def test_reconstitution_n_ecrit_pas_de_stock_fantome():
    """Le backfill traverse 400 jours dont trois seulement portent un snapshot :
    il ne doit écrire une valeur de stock QUE pour ces trois-là."""
    async def corps(factory):
        await indicateurs.reconstituer(date(2026, 8, 10), date(2026, 8, 20))
        from sqlalchemy import select
        from db.models import IndicatorSnapshotModel
        async with factory() as session:
            lignes = (await session.execute(
                select(IndicatorSnapshotModel).where(IndicatorSnapshotModel.cle == "pipe_brut")
            )).scalars().all()
        return sorted(l.snapshot_date for l in lignes)
    jours = asyncio.run(_dans_la_base(
        corps, snapshots=[(date(2026, 8, 13), 1000.0, date(2026, 12, 31)),
                          (date(2026, 8, 18), 900.0, date(2026, 12, 31))]
    ))
    assert jours == [date(2026, 8, 13), date(2026, 8, 18)]


def test_reconstitution_n_ecrase_pas_une_mesure():
    """Une valeur relevée le jour dit prime sur une reconstitution approchée."""
    async def corps(factory):
        await indicateurs.enregistrer(date(2026, 8, 15), {"ca_commande_ytd": 42.0}, "mesure")
        await indicateurs.reconstituer(date(2026, 8, 15), date(2026, 8, 15))
        from sqlalchemy import select
        from db.models import IndicatorSnapshotModel
        async with factory() as session:
            ligne = (await session.execute(
                select(IndicatorSnapshotModel).where(
                    IndicatorSnapshotModel.cle == "ca_commande_ytd",
                    IndicatorSnapshotModel.snapshot_date == date(2026, 8, 15),
                )
            )).scalars().one()
        return ligne.valeur, ligne.origine
    valeur, origine = asyncio.run(_dans_la_base(corps))
    assert (valeur, origine) == (42.0, "mesure")


# ── Comparaison ──────────────────────────────────────────────────────────────

def test_delta_refuse_de_franchir_la_remise_a_zero():
    """Comparer le 2 janvier au 31 décembre présenterait la remise à zéro de
    l'exercice comme le mouvement d'une nuit."""
    async def corps(_):
        await indicateurs.enregistrer(date(2025, 12, 31), {"ca_commande_ytd": 9999.0}, "mesure")
        await indicateurs.enregistrer(date(2026, 1, 1), {"ca_commande_ytd": 0.0}, "mesure")
        return await indicateurs.delta(["ca_commande_ytd"], as_of=date(2026, 1, 1))
    bloc = asyncio.run(_dans_la_base(corps))["ca_commande_ytd"]
    assert bloc["j1"] is None
    assert indicateurs.formater(bloc, "j1") == ""


def test_delta_recule_avant_d_avancer():
    """Pour un horizon « 7 jours » visant le 20/08, avec des points au 13/08 et
    au 26/08, une recherche symétrique retiendrait le 26/08 — à un seul jour
    d'aujourd'hui — et présenterait une variation d'une nuit comme celle d'une
    semaine."""
    async def corps(_):
        await indicateurs.enregistrer(date(2026, 8, 13), {"backlog": 100.0}, "mesure")
        await indicateurs.enregistrer(date(2026, 8, 26), {"backlog": 180.0}, "mesure")
        await indicateurs.enregistrer(AUJOURD_HUI, {"backlog": 200.0}, "mesure")
        return await indicateurs.delta(["backlog"], as_of=AUJOURD_HUI)
    bloc = asyncio.run(_dans_la_base(corps))["backlog"]
    assert bloc["semaine_depuis"] == "2026-08-13"
    assert bloc["semaine"] == 100.0


def test_delta_avance_en_dernier_recours():
    """Si rien n'existe en amont de la cible, un point légèrement postérieur
    reste préférable au silence — un horizon « 30 j » visant le 27/07 répond
    exactement à la question avec un point au 28/07."""
    async def corps(_):
        await indicateurs.enregistrer(date(2026, 7, 28), {"backlog": 100.0}, "mesure")
        await indicateurs.enregistrer(AUJOURD_HUI, {"backlog": 150.0}, "mesure")
        return await indicateurs.delta(["backlog"], as_of=AUJOURD_HUI)
    bloc = asyncio.run(_dans_la_base(corps))["backlog"]
    assert bloc["mois_depuis"] == "2026-07-28"
    assert bloc["mois"] == 50.0


def test_delta_ne_se_compare_jamais_a_lui_meme():
    """Un point daté d'aujourd'hui donnerait un mouvement nul trompeur."""
    async def corps(_):
        await indicateurs.enregistrer(AUJOURD_HUI, {"backlog": 200.0}, "mesure")
        return await indicateurs.delta(["backlog"], as_of=AUJOURD_HUI)
    bloc = asyncio.run(_dans_la_base(corps))["backlog"]
    assert bloc["j1"] is None and bloc["semaine"] is None and bloc["mois"] is None


def test_delta_sans_historique_ne_rend_pas_zero():
    async def corps(_):
        return await indicateurs.delta(["ca_commande_ytd"], as_of=AUJOURD_HUI)
    bloc = asyncio.run(_dans_la_base(corps))["ca_commande_ytd"]
    assert bloc["valeur"] is not None      # calculé à la volée
    assert bloc["j1"] is None              # mais rien à quoi le comparer


# ── Mise en forme ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bloc, horizon, attendu", [
    ({"unite": "xof", "j1": 85_000_000, "j1_jours": 1}, "j1", " (▲ 85 M FCFA vs hier)"),
    ({"unite": "xof", "j1": -85_000_000, "j1_jours": 1}, "j1", " (▼ 85 M FCFA vs hier)"),
    ({"unite": "xof", "j1": 0, "j1_jours": 1}, "j1", " (stable vs hier)"),
    ({"unite": "nb", "j1": 5, "j1_jours": 1}, "j1", " (▲ 5 vs hier)"),
    ({"unite": "xof", "j1": None}, "j1", ""),
    # Sous le million, l'arrondi rendrait « ▲ 0 M FCFA » : « stable » est plus
    # juste et plus lisible qu'un mouvement affiché comme nul.
    ({"unite": "xof", "j1": 400_000, "j1_jours": 1}, "j1", " (stable vs hier)"),
])
def test_formater(bloc, horizon, attendu):
    assert indicateurs.formater(bloc, horizon) == attendu


def test_formater_date_une_comparaison_decalee():
    """Une comparaison silencieusement décalée est pire que pas de comparaison :
    elle est invérifiable par le lecteur."""
    bloc = {"unite": "xof", "semaine": 4_000_000, "semaine_depuis": "2026-08-13",
            "semaine_jours": 14}
    assert indicateurs.formater(bloc, "semaine") == " (▲ 4 M FCFA depuis le 13/08)"


# ── Ligne de cadence (6e ligne du résumé) ────────────────────────────────────

def test_ligne_cadence_dit_les_trois_horizons():
    bloc = {"unite": "xof", "valeur": 6_128_000_000,
            "j1": 0, "j1_jours": 1, "semaine": -12_000_000, "semaine_jours": 7,
            "mois": 17_000_000, "mois_jours": 30}
    assert indicateurs.ligne_cadence(bloc, "CA commandé") == (
        "CA commandé : 6 128 M FCFA — stable vs hier, ▼ 12 M FCFA sur 7 j, "
        "▲ 17 M FCFA sur 30 j."
    )


def test_ligne_cadence_tait_les_horizons_absents():
    """Un stock historisé depuis cinq jours n'a pas de point à trente jours. La
    ligne dit ce qu'elle sait — elle ne comble pas le trou par un « stable »,
    qui se lirait comme une mesure."""
    bloc = {"unite": "xof", "valeur": 900_000_000,
            "j1": 5_000_000, "j1_jours": 1, "semaine": None, "mois": None}
    assert indicateurs.ligne_cadence(bloc, "Pipe actif") == (
        "Pipe actif : 900 M FCFA — ▲ 5 M FCFA vs hier."
    )


@pytest.mark.parametrize("bloc", [
    None,                                                     # indicateur absent
    {"unite": "xof", "valeur": None},                         # valeur du jour introuvable
    {"unite": "xof", "valeur": 10, "j1": None, "semaine": None, "mois": None},
])
def test_ligne_cadence_disparait_quand_rien_nest_mesurable(bloc):
    """Le résumé retombe à ses cinq lignes plutôt que d'en porter une sixième
    qui n'annonce aucun mouvement — une ligne muette se lit comme « rien n'a
    bougé », ce qui est une affirmation, pas une absence."""
    assert indicateurs.ligne_cadence(bloc, "CA commandé") == ""


def test_ligne_cadence_et_puce_disent_le_meme_mouvement():
    """Les deux passent par `_mouvement` : le jour où l'un des deux arrondit
    autrement, le lecteur voit deux chiffres pour un seul écart."""
    bloc = {"unite": "xof", "valeur": 6_128_000_000, "j1": 85_000_000, "j1_jours": 1}
    suffixe = indicateurs.formater(bloc, "j1")
    assert suffixe == " (▲ 85 M FCFA vs hier)"
    assert suffixe.strip()[1:-1] in indicateurs.ligne_cadence(bloc, "CA commandé")


def test_catalogue_est_coherent():
    """Tout indicateur adossé à un snapshot doit déclarer sa table, sans quoi le
    garde-fou de `calculer` ne s'applique pas et le stock rend 0 en silence."""
    for cle, ind in indicateurs.CATALOGUE.items():
        assert ind.unite in ("xof", "nb", "pct", "jours"), cle
        assert ind.nature in ("flux", "stock"), cle
        assert ind.sql_historique or ind.sql_jour, cle
        if ind.nature == "flux":
            assert ind.remise_a_zero in ("annuelle", "mensuelle"), cle
            assert ind.source_snapshot is None, cle
        if "pipe" in cle or cle.startswith("nb_opportunites") or cle in ("backlog", "reste_a_encaisser"):
            assert ind.source_snapshot, cle
