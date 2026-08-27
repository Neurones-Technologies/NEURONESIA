"""Seuils réglables par rôle — le mécanisme qui fait servir un moteur unique à
quatre briefings différents.

Ce qui doit rester vrai quoi qu'il arrive : une table vide reproduit exactement
le comportement d'avant, et une valeur absurde est REFUSÉE plutôt que rognée en
silence — un réglage rogné paraît pris en compte et ne l'est pas.
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base
from db.models import BriefingSeuilModel
from modules.uc_briefing import seuils


async def _dans_la_base(corps):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import db.database as database
    originaux = (database.AsyncSessionLocal, seuils.AsyncSessionLocal)
    database.AsyncSessionLocal = factory
    seuils.AsyncSessionLocal = factory
    seuils.invalidate_cache()
    try:
        return await corps(factory)
    finally:
        database.AsyncSessionLocal, seuils.AsyncSessionLocal = originaux
        seuils.invalidate_cache()
        await engine.dispose()


def test_table_vide_reproduit_les_defauts():
    """Rien à migrer, rien à initialiser : l'absence de ligne EST le défaut."""
    async def corps(_):
        return await seuils.charger("dg")
    valeurs = asyncio.run(_dans_la_base(corps))
    assert valeurs["concentration_top5_pct"] == 50
    assert valeurs["materialisation_pct"] == 80


def test_les_roles_ne_partagent_pas_le_meme_seuil():
    """Le sens même du mécanisme : la même donnée, deux moments d'alerte.
    Un commercial travaille à 30 jours d'horizon, un directeur commercial à 60."""
    async def corps(_):
        return (await seuils.charger("commercial"), await seuils.charger("dir_commercial"))
    terrain, direction = asyncio.run(_dans_la_base(corps))
    assert terrain["echeance_fenetre_jours"] == 30
    assert direction["echeance_fenetre_jours"] == 60


def test_valeur_hors_bornes_est_refusee_et_non_rognee():
    async def corps(_):
        return await seuils.enregistrer(
            "dg", {"concentration_top5_pct": 400, "materialisation_pct": 65}, "test@s2i"
        )
    res = asyncio.run(_dans_la_base(corps))
    assert res["retenues"] == {"materialisation_pct": 65.0}
    assert "concentration_top5_pct" in res["refusees"]
    # Le seuil refusé garde sa valeur d'origine : rien n'a été à moitié écrit.
    assert res["seuils"]["concentration_top5_pct"] == 50


def test_seuil_inconnu_est_signale_et_non_avale():
    async def corps(_):
        return await seuils.enregistrer("dg", {"invente": 1}, "test@s2i")
    res = asyncio.run(_dans_la_base(corps))
    assert res["refusees"]["invente"] == "seuil inconnu"


def test_valeur_non_numerique_est_refusee():
    async def corps(_):
        return await seuils.enregistrer("dg", {"materialisation_pct": "beaucoup"}, "test@s2i")
    res = asyncio.run(_dans_la_base(corps))
    assert res["retenues"] == {}
    assert "materialisation_pct" in res["refusees"]


def test_enregistrer_puis_relire():
    async def corps(_):
        await seuils.enregistrer("dir_financier", {"retard_relance_jours": 45}, "daf@s2i")
        return await seuils.charger("dir_financier")
    assert asyncio.run(_dans_la_base(corps))["retard_relance_jours"] == 45.0


def test_reinitialiser_rend_les_defauts():
    async def corps(_):
        await seuils.enregistrer("dg", {"concentration_top5_pct": 25}, "dg@s2i")
        avant = (await seuils.charger("dg"))["concentration_top5_pct"]
        await seuils.reinitialiser("dg")
        return avant, (await seuils.charger("dg"))["concentration_top5_pct"]
    avant, apres = asyncio.run(_dans_la_base(corps))
    assert (avant, apres) == (25.0, 50)


def test_ligne_orpheline_est_ignoree_sans_erreur():
    """Une clé retirée du code laisse sa ligne en base : elle doit être ignorée
    à la lecture, jamais coûter le briefing (même doctrine que les préférences)."""
    async def corps(factory):
        async with factory() as session:
            session.add(BriefingSeuilModel(role="dg", cle="cle_disparue", valeur=1.0))
            session.add(BriefingSeuilModel(role="role_disparu", cle="materialisation_pct",
                                           valeur=1.0))
            await session.commit()
        seuils.invalidate_cache()
        return await seuils.charger("dg")
    valeurs = asyncio.run(_dans_la_base(corps))
    assert "cle_disparue" not in valeurs
    assert valeurs["materialisation_pct"] == 80


def test_valeur_corrompue_en_base_retombe_sur_le_defaut():
    """Une valeur écrite hors bornes par un autre chemin ne doit pas ressortir."""
    async def corps(factory):
        async with factory() as session:
            session.add(BriefingSeuilModel(role="dg", cle="materialisation_pct", valeur=9999.0))
            await session.commit()
        seuils.invalidate_cache()
        return await seuils.charger("dg")
    assert asyncio.run(_dans_la_base(corps))["materialisation_pct"] == 80


def test_catalogue_expose_valeur_defaut_et_modification():
    async def corps(_):
        await seuils.enregistrer("dg", {"concentration_top5_pct": 30}, "dg@s2i")
        return await seuils.catalogue_pour("dg")
    lignes = {ligne["cle"]: ligne for ligne in asyncio.run(_dans_la_base(corps))}
    assert lignes["concentration_top5_pct"]["valeur"] == 30.0
    assert lignes["concentration_top5_pct"]["defaut"] == 50
    assert lignes["concentration_top5_pct"]["modifie"] is True
    assert lignes["materialisation_pct"]["modifie"] is False
    # `effet` dit ce que le seuil DÉCLENCHE : c'est la seule description utile
    # à qui règle, et l'écran de réglages n'en détient pas de copie.
    assert all(ligne["effet"] for ligne in lignes.values())


def test_chaque_role_du_briefing_a_ses_defauts():
    """Un rôle absent de DEFAUTS n'aurait aucun seuil propre et retomberait
    silencieusement sur ceux du catalogue commun."""
    from modules.uc_briefing.service import ROLES
    assert set(ROLES) == set(seuils.DEFAUTS)


def test_base_illisible_ne_coute_que_les_reglages():
    """Un échec de lecture doit coûter les seuils, jamais le briefing.

    `service.generate` lit désormais la base DEUX fois avant de composer — les
    préférences puis les seuils. Ajouter une source d'échec à cet endroit pour
    un simple confort de réglage serait un mauvais marché : les défauts du code
    reproduisent exactement le comportement d'avant, donc le repli est gratuit.
    """
    async def corps(_):
        async def _explose():
            raise RuntimeError("briefing_seuils inaccessible")
        original = seuils._lire
        seuils._lire = _explose
        seuils.invalidate_cache()
        try:
            return await seuils.charger_tous()
        finally:
            seuils._lire = original

    valeurs = asyncio.run(_dans_la_base(corps))
    assert set(valeurs) == set(seuils.DEFAUTS)
    assert valeurs["dg"]["concentration_top5_pct"] == 50
    assert valeurs["commercial"]["echeance_fenetre_jours"] == 30
