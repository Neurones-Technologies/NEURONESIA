"""Agrégations propres au briefing : balance âgée, relances, DSO, dérive,
sous-traitance, visibilité, book-to-bill.

Le fil conducteur : aucune de ces fonctions ne doit rendre un chiffre plutôt
qu'un aveu d'impossibilité. Un dénominateur minuscule, un échantillon de trois
factures ou une source vide produisent tous, si on n'y prend garde, un nombre
parfaitement présentable et parfaitement faux.
"""
import asyncio
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base
from db.models import ClientModel, DossierModel, InvoiceModel, PurchaseOrderModel, SaleOrderModel
from modules.uc_briefing import analyses

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
    originaux = (database.AsyncSessionLocal, analyses.AsyncSessionLocal)
    database.AsyncSessionLocal = factory
    analyses.AsyncSessionLocal = factory
    try:
        return await corps()
    finally:
        database.AsyncSessionLocal, analyses.AsyncSessionLocal = originaux
        await engine.dispose()


def _facture(ref, client, montant, residuel, echeance, emise=date(2026, 1, 1), reglee=None):
    return InvoiceModel(
        invoice_id=ref, client_id=client, amount=montant, amount_residual=residuel,
        status="paid" if reglee else "pending", invoice_date=_dt(emise),
        due_date=_dt(echeance), payment_date=_dt(reglee) if reglee else None,
    )


def _creances():
    return [
        ClientModel(client_id="1", name="BAD"),
        ClientModel(client_id="2", name="NEURONES TECHNOLOGIES BENIN"),
        _facture("f1", "1", 100, 100, date(2026, 9, 30)),          # à échoir
        _facture("f2", "1", 200, 200, date(2026, 8, 15)),          # 12 j
        _facture("f3", "1", 300, 300, date(2026, 7, 15)),          # 43 j
        _facture("f4", "1", 400, 400, date(2026, 6, 15)),          # 73 j
        _facture("f5", "1", 500, 500, date(2026, 1, 15)),          # 224 j → contentieux
        _facture("f6", "2", 50, 50, date(2026, 1, 15)),            # intragroupe
        # Soldée : ne doit apparaître dans AUCUNE tranche.
        _facture("f7", "1", 900, 0, date(2026, 1, 15), reglee=date(2026, 3, 1)),
        # Annulée : idem.
        InvoiceModel(invoice_id="f8", client_id="1", amount=700, amount_residual=700,
                     status="cancelled", invoice_date=_dt(date(2026, 1, 1)),
                     due_date=_dt(date(2026, 1, 15))),
    ]


def test_balance_agee_ventile_sans_recouvrement():
    async def corps():
        return await analyses.balance_agee(AUJOURD_HUI, contentieux_jours=90)
    b = asyncio.run(_dans_la_base(corps, _creances))

    t = b["tranches"]
    assert t["a_echoir"]["montant_xof"] == 100
    assert t["j0_30"]["montant_xof"] == 200
    assert t["j30_60"]["montant_xof"] == 300
    assert t["j60_90"]["montant_xof"] == 400
    assert t["j90_plus"]["montant_xof"] == 550         # f5 + f6
    # Les cinq tranches partitionnent : aucune facture comptée deux fois, aucune
    # perdue entre deux bornes.
    assert sum(v["montant_xof"] for v in t.values()) == b["montant_total_xof"]
    assert b["montant_total_xof"] == 1550              # ni la soldée ni l'annulée


def test_balance_agee_partitionne_quel_que_soit_le_seuil():
    """Le contentieux RECOUPE les tranches, il ne s'y ajoute pas.

    Traité comme une sixième tranche, il fonctionnait à 90 j et faisait
    totaliser 145 % de l'encours à 30 j — la puce énumérant les tranches
    comptait alors trois fois les mêmes factures.
    """
    async def corps():
        return [await analyses.balance_agee(AUJOURD_HUI, seuil)
                for seuil in (30, 60, 90, 180)]
    for b in asyncio.run(_dans_la_base(corps, _creances)):
        assert sum(v["montant_xof"] for v in b["tranches"].values()) == b["montant_total_xof"]
        assert b["contentieux"]["montant_xof"] <= b["montant_total_xof"]


def test_balance_agee_isole_l_intragroupe_sans_le_retirer():
    """Le total doit rester rapprochable de la comptabilité, mais une créance
    sur une filiale n'est pas un risque de même nature qu'une créance externe."""
    async def corps():
        return await analyses.balance_agee(AUJOURD_HUI)
    b = asyncio.run(_dans_la_base(corps, _creances))
    assert b["intragroupe"]["montant_xof"] == 50
    assert b["intragroupe"]["nb"] == 1
    assert b["montant_total_xof"] == 1550              # toujours inclus


def test_balance_agee_suit_le_seuil_de_contentieux():
    """La DAF place le contentieux à 90 j, la DG plus tôt — même donnée."""
    async def corps():
        return (await analyses.balance_agee(AUJOURD_HUI, 90),
                await analyses.balance_agee(AUJOURD_HUI, 30))
    large, strict = asyncio.run(_dans_la_base(corps, _creances))
    assert large["contentieux"]["montant_xof"] == 550
    assert strict["contentieux"]["montant_xof"] == 1250   # f3+f4+f5+f6
    # Les tranches, elles, ne bougent pas d'un seuil à l'autre.
    assert large["tranches"] == strict["tranches"]


def test_relances_groupent_par_client():
    """On ne passe pas cinq appels au même débiteur pour cinq factures."""
    async def corps():
        return await analyses.relances_du_jour(AUJOURD_HUI, retard_min_jours=30)
    r = asyncio.run(_dans_la_base(corps, _creances))
    assert r["nb_clients"] == 2                       # BAD et l'intragroupe
    tete = r["top"][0]
    assert tete["client"] == "BAD"
    assert tete["nb_factures"] == 3                   # f3, f4, f5
    assert tete["montant_xof"] == 1200
    assert tete["retard_max_jours"] == 224
    assert any(ligne["intragroupe"] for ligne in r["top"])


def _reglements():
    return [
        # Fenêtre récente : réglée 100 jours après émission.
        _facture("r1", "1", 1000, 0, date(2026, 3, 1),
                 emise=date(2026, 1, 1), reglee=date(2026, 4, 11)),
        # Fenêtre précédente : réglée 10 jours après émission.
        _facture("r2", "1", 1000, 0, date(2025, 3, 1),
                 emise=date(2025, 1, 1), reglee=date(2025, 1, 11)),
    ]


def test_dso_compare_a_la_periode_precedente():
    async def corps():
        return await analyses.dso_glissant(AUJOURD_HUI, fenetre_mois=12)
    d = asyncio.run(_dans_la_base(corps, _reglements))
    assert d["mesurable"] is True
    assert d["dso_jours"] == 100.0
    assert d["dso_precedent_jours"] == 10.0
    assert d["ecart_jours"] == 90.0


def test_dso_avoue_un_echantillon_trop_mince():
    """« Le DSO s'améliore de 40 jours » sur trois factures est le type même du
    chiffre crédible et faux."""
    async def corps():
        return await analyses.dso_glissant(AUJOURD_HUI, fenetre_mois=12)
    assert asyncio.run(_dans_la_base(corps, _reglements))["robuste"] is False


def test_dso_sans_reglement_ne_rend_pas_zero():
    async def corps():
        return await analyses.dso_glissant(AUJOURD_HUI)
    d = asyncio.run(_dans_la_base(corps, lambda: []))
    assert d["mesurable"] is False
    assert d["raison"]


def _dossiers():
    return [
        # Dépense définitive au-delà de la prévision → dérive.
        DossierModel(dossier_ref="DC/1", odoo_id=1, client_name="SGCI",
                     ca_provisoire=1000.0, depense_provisoire=800.0,
                     ca_definitif=1000.0, depense_definitive=1000.0,
                     perc_marge_previsionnelle=20.0, perc_marge_definitive=0.0),
        # Sous le seuil → hors liste.
        DossierModel(dossier_ref="DC/2", odoo_id=2, client_name="CIE",
                     ca_provisoire=1000.0, depense_provisoire=800.0,
                     ca_definitif=1000.0, depense_definitive=400.0),
        # CA provisoire dérisoire, CA définitif réel : le piège du dénominateur.
        DossierModel(dossier_ref="DC/3", odoo_id=3, client_name="BAD",
                     ca_provisoire=2.0, depense_provisoire=600.0,
                     ca_definitif=1800.0, depense_definitive=600.0),
        PurchaseOrderModel(order_id="po1", client_id="9", client_name="WESTCON", name="PO/1",
                           amount=660.0, state="purchase", dossier_id="DC/3"),
        # Achat non rattaché : il doit compter dans les orphelins.
        PurchaseOrderModel(order_id="po2", client_id="9", client_name="WESTCON", name="PO/2",
                           amount=50.0, state="purchase", dossier_id=None),
    ]


def test_derive_budgetaire_retient_les_depassements():
    async def corps():
        return await analyses.derive_budgetaire(seuil_consommation_pct=90)
    d = asyncio.run(_dans_la_base(corps, _dossiers))
    assert d["nb"] == 2                                # DC/1 (125 %) et DC/3 (100 %)
    refs = {ligne["ref"] for ligne in d["top"]}
    assert refs == {"DC/1", "DC/3"}
    assert d["reserve"]                                # la puce doit la porter


def test_sous_traitance_evite_le_denominateur_derisoire():
    """Le CA provisoire de DC/3 vaut 2 pour 1 800 de définitif : le prendre
    d'office affichait « sous-traitance à 33 407 % du CA ». Un pourcentage à
    cinq chiffres dans un briefing de direction ruine toute la page."""
    async def corps():
        return await analyses.sous_traitance_par_dossier()
    st = asyncio.run(_dans_la_base(corps, _dossiers))
    ligne = st["top"][0]
    assert ligne["ref"] == "DC/3"
    assert ligne["base_ca"] == "définitif"
    assert ligne["poids_sur_ca_pct"] == 36.7           # 660 / 1800
    assert ligne["engagement_depasse_ca"] is False


def test_sous_traitance_publie_sa_couverture():
    """Un engagement « total » calculé sur 71 % des achats n'est pas un total."""
    async def corps():
        return await analyses.sous_traitance_par_dossier()
    st = asyncio.run(_dans_la_base(corps, _dossiers))
    assert st["couverture_pct"] == 50.0                # 1 rattaché sur 2
    assert st["nb_achats_orphelins"] == 1


def _carnet():
    return [
        DossierModel(dossier_ref="DC/1", odoo_id=1, client_name="CIE", backlog=1200.0),
        InvoiceModel(invoice_id="v1", client_id="1", amount=300.0, amount_residual=0.0,
                     status="paid", invoice_date=_dt(date(2026, 7, 1)),
                     due_date=_dt(date(2026, 8, 1))),
        InvoiceModel(invoice_id="v2", client_id="1", amount=300.0, amount_residual=0.0,
                     status="paid", invoice_date=_dt(date(2026, 8, 1)),
                     due_date=_dt(date(2026, 9, 1))),
        SaleOrderModel(order_id="so1", client_id="1", client_name="CIE", name="FP/1",
                       amount=1200.0, state="sale", date_order=_dt(date(2026, 7, 15))),
    ]


def test_visibilite_carnet():
    async def corps():
        return await analyses.visibilite_carnet(AUJOURD_HUI, fenetre_mois=3)
    v = asyncio.run(_dans_la_base(corps, _carnet))
    assert v["mesurable"] is True
    assert v["facture_mensuel_moyen_xof"] == 200.0     # 600 sur 3 mois
    assert v["mois_visibilite"] == 6.0                 # 1200 / 200


def test_visibilite_sans_facturation_ne_rend_pas_l_infini():
    async def corps():
        return await analyses.visibilite_carnet(AUJOURD_HUI, fenetre_mois=1)
    v = asyncio.run(_dans_la_base(
        corps, lambda: [DossierModel(dossier_ref="DC/1", odoo_id=1, backlog=1200.0)]
    ))
    assert v["mesurable"] is False
    assert v["backlog_xof"] == 1200.0                  # le numérateur reste dit


def test_book_to_bill():
    async def corps():
        return await analyses.book_to_bill(AUJOURD_HUI, fenetre_mois=12)
    b = asyncio.run(_dans_la_base(corps, _carnet))
    assert b["ratio"] == 2.0                           # 1200 commandés / 600 facturés
    assert b["reserve"]                                # TTC des deux côtés
