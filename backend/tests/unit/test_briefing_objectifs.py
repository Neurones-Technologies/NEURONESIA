"""Objectifs dans le briefing : depuis l'import nt360, la puce « CA facturé » et
la répartition par commercial donnent un taux d'atteinte — toujours accompagné
de la part de l'année écoulée, sans quoi un réalisé d'octobre rapporté à une
cible annuelle pleine se lit comme un échec."""
import asyncio
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base
from db.models import CommercialObjectiveModel, Nt360ObjectifModel
from modules.uc_briefing import analyses, facts

OBJ = {"annee": 2026, "commandes_xof": 13_800_000_000.0, "facturation_xof": 15_000_000_000.0,
       "marge_xof": None, "origine_commandes": "nt360", "nb_objectifs_individuels": 0,
       "part_annee_ecoulee_pct": 79.7}
DELTAS = {
    "ca_facture_mois": {"valeur": 400_000_000.0, "reserve": ""},
    "ca_facture_ytd": {"valeur": 4_316_000_000.0},
    "ca_commande_ytd": {"valeur": 8_380_000_000.0},
    "encaissements_mois": {"valeur": 0},
}


def _puce_facture(objectifs):
    f, p = {}, facts.Puces("dir_financier")
    facts._puce_ca_facture(f, p, DELTAS, objectifs)
    return f, p.liste()[0]


def test_puce_facture_donne_le_taux_datteinte_et_lannee_ecoulee():
    f, texte = _puce_facture(OBJ)
    assert f["objectif_saisi"] is True
    assert f["atteinte_facturation_pct"] == 28.8 and f["atteinte_commandes_pct"] == 60.7
    assert "À 80 % de l'année écoulée, objectif 2026 de facturation à 29 %" in texte
    assert "de commandes à 61 % (13,8 Md FCFA)" in texte    # espace fine insécable de fcfa()
    assert "aucun objectif" not in texte.lower()


def test_puce_facture_sans_objectif_le_dit():
    f, texte = _puce_facture(None)
    assert f["objectif_saisi"] is False
    assert "Aucun objectif n'étant saisi pour l'exercice" in texte


def test_repartition_par_commercial_cite_lobjectif_dequipe():
    f, sortie = {}, []
    par_commercial = [{"commercial": "A", "ca_total_xof": 6e9}, {"commercial": "B", "ca_total_xof": 2.38e9}]
    facts._couverture_objectifs(f, sortie, par_commercial, 2026, OBJ)
    assert f["couverture_objectif_saisi"] is True and f["couverture_atteinte_equipe_pct"] == 60.7
    assert "objectif d'équipe 2026" in sortie[0] and "sans objectif individuel" in sortie[0]


def test_objectifs_annuels_lit_les_deux_sources_et_lannee_ecoulee():
    async def corps():
        engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False},
                                     poolclass=StaticPool)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            for ref, cible, sup in (("CI", 8.8e9, False), ("BF", 5e9, False), ("CI", 8e9, True)):
                s.add(CommercialObjectiveModel(
                    scope="equipe", scope_ref=ref, kind="ca", period_type="annee", period_year=2026,
                    period_index=0, target_amount_xof=cible, target_count=0, revision=1,
                    superseded=sup, note="", created_by="nt360", created_at=datetime(2026, 10, 1)))
            s.add_all([
                Nt360ObjectifModel(id="CI", fiscal_year=2026, scope="global", filiale="CI",
                                   target_cas=8.8e9, target_invoiced=10e9, target_margin=2e9),
                Nt360ObjectifModel(id="BF", fiscal_year=2026, scope="global", filiale="BF",
                                   target_cas=5e9, target_invoiced=5e9, target_margin=1.25e9),
            ])
            await s.commit()
        orig = analyses.AsyncSessionLocal
        analyses.AsyncSessionLocal = factory
        try:
            return (await analyses.objectifs_annuels(2026, date(2026, 10, 19)),
                    await analyses.objectifs_annuels(2025, date(2026, 10, 19)))
        finally:
            analyses.AsyncSessionLocal = orig
            await engine.dispose()
    o, vide = asyncio.run(corps())
    assert o["commandes_xof"] == 13.8e9                     # révision archivée exclue
    assert o["facturation_xof"] == 15e9 and o["marge_xof"] == 3.25e9
    assert o["origine_commandes"] == "nt360" and o["part_annee_ecoulee_pct"] == 80.0    # 292 j sur 365
    assert vide is None
