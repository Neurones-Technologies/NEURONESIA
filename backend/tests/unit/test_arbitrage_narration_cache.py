"""Rédactions LLM d'un dossier d'arbitrage : parallélisme, cache, et refus de
mettre un repli déterministe en cache.

Quatre propriétés à ne pas perdre :

  1. Les deux appels modèle (avocat du contraire, formulation de l'option C) ne
     se lisent pas l'un l'autre : ils doivent partir ENSEMBLE. Les enchaîner
     doublait le temps d'ouverture d'un dossier.
  2. Rouvrir le même dossier ne doit pas repayer les appels — mais la clé doit
     bouger dès qu'un chiffre cité change ou qu'une décision revue vient
     s'ajouter à la mémoire, sinon la narration devient périmée en silence.
  3. Un repli déterministe (modèle indisponible ou réponse illisible) ne doit
     JAMAIS être enregistré : ce serait faire durer un incident de quelques
     secondes jusqu'au prochain changement de chiffre — c'est-à-dire
     potentiellement des jours, depuis que la persistance a remplacé le TTL.
  4. La rédaction survit au processus : elle est en base
     (`arbitrage_narrations`), pas en mémoire. C'est ce qui la rend partagée
     entre les deux workers uvicorn et conservée à travers un redéploiement.

Chaque narration tourne dans son propre `asyncio.run` — d'où la base sur
FICHIER temporaire plutôt qu'en mémoire (une connexion aiosqlite est liée à la
boucle qui l'a ouverte) et la remise à zéro des verrous entre deux tests.
"""
import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.services import ttl_cache
from db.database import Base
from db.models import ArbitrageNarrationModel
from modules.uc_arbitrage import narratif, narration_store


@pytest.fixture(autouse=True)
def cache_vide(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'narrations.db'}")

    async def _creer():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_creer())

    fabrique_origine = narration_store.AsyncSessionLocal
    narration_store.AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    narration_store._LOCKS.clear()
    ttl_cache._STORE.clear()
    yield
    narration_store._LOCKS.clear()
    ttl_cache._STORE.clear()
    narration_store.AsyncSessionLocal = fabrique_origine
    asyncio.run(engine.dispose())


def _lignes_en_base() -> list[ArbitrageNarrationModel]:
    from sqlalchemy import select

    async def _lire():
        async with narration_store.AsyncSessionLocal() as session:
            return (await session.execute(select(ArbitrageNarrationModel))).scalars().all()

    return asyncio.run(_lire())


class LLMSimule:
    """Compte les appels et mesure combien tournent en même temps."""

    def __init__(self, latence: float = 0.05, casse: bool = False):
        self.latence, self.casse = latence, casse
        self.appels, self.en_vol, self.max_en_vol = 0, 0, 0

    async def generate(self, system, user, max_tokens, temperature):
        self.appels += 1
        self.en_vol += 1
        self.max_en_vol = max(self.max_en_vol, self.en_vol)
        try:
            await asyncio.sleep(self.latence)
            if self.casse:
                raise RuntimeError("modèle indisponible")
            if "avocat du contraire" in system:
                return '{"raisons": ["objection A", "objection B"]}'
            return '{"titre": "Apurement échelonné", "argumentaire": "Deux phrases."}'
        finally:
            self.en_vol -= 1


def _dossier(**surcharges) -> dict:
    base = {
        "subject_ref": "BICICI",
        "subject_label": "BICICI — 3 facture(s) échue(s) contre cross-sell en cours",
        "enjeu_xof": 318_942_584,
        "impaye_xof": 42_000_000,
        "profil_payeur": {
            "classe": "degradation",
            "lecture": "règle habituellement à 20 j, passé à 36 j",
            "delai_ancien_jours": 20,
            "delai_recent_jours": 36,
            "nb_factures_payees": 12,
        },
    }
    return {**base, **surcharges}


_OPTION = {
    "code": "C",
    "titre": "Échelonner l'apurement sur 108 j et débloquer sous condition",
    "description": "3 échéances de 14 M FCFA, une tous les 36 j.",
}

_PLAN = {
    "nb_echeances": 3,
    "tranche_xof": 14_000_000,
    "pas_jours": 36,
    "horizon_jours": 108,
    "delai_reference_jours": 36,
    "declencheur": "reprise des engagements dès la première échéance encaissée",
    "methode": "calibré sur le délai de paiement réellement observé",
}


def _narration(llm, dossier=None, decisions=None, plan=_PLAN, option=None):
    return asyncio.run(narratif.build_dossier_narration(
        llm, dossier or _dossier(), option or _OPTION, decisions, plan,
    ))


def test_les_deux_redactions_partent_ensemble():
    llm = LLMSimule()
    raisons, redaction = _narration(llm)

    assert llm.appels == 2
    assert llm.max_en_vol == 2, "les deux appels modèle se sont enchaînés au lieu de partir ensemble"
    assert raisons == ["objection A", "objection B"]
    assert redaction["argumentaire"] == "Deux phrases."
    assert redaction["redige_par"] == "ia"


def test_sans_echeancier_un_seul_appel():
    """Pas de plan calculable = pas d'option C à formuler."""
    llm = LLMSimule()
    raisons, redaction = _narration(llm, plan=None)

    assert llm.appels == 1
    assert redaction is None
    assert raisons == ["objection A", "objection B"]


def test_reouverture_ne_repaye_pas_le_modele():
    llm = LLMSimule()
    premier = _narration(llm)
    assert llm.appels == 2

    second = _narration(llm)
    assert llm.appels == 2, "le dossier rouvert a rappelé le modèle"
    assert second == premier


def test_le_cache_ne_fuit_pas_entre_requetes():
    """Le résultat servi est une copie : un appelant qui le modifie ne corrompt
    pas ce que verra la requête suivante."""
    llm = LLMSimule()
    raisons, redaction = _narration(llm)
    raisons.append("ajout local")
    redaction["argumentaire"] = "écrasé localement"

    raisons2, redaction2 = _narration(llm)
    assert raisons2 == ["objection A", "objection B"]
    assert redaction2["argumentaire"] == "Deux phrases."


@pytest.mark.parametrize("surcharge", [
    {"enjeu_xof": 999_000_000},
    {"impaye_xof": 900_000_000},
    {"subject_ref": "MTN CI"},
    {"subject_label": "BICICI — 9 facture(s) échue(s) contre renouvellement en cours"},
])
def test_un_chiffre_cite_qui_change_invalide_le_cache(surcharge):
    """Les montants et le libellé passent dans le prompt : la narration ne doit
    pas survivre à leur changement, sinon elle cite des chiffres périmés."""
    llm = LLMSimule()
    _narration(llm)
    assert llm.appels == 2

    _narration(llm, dossier=_dossier(**surcharge))
    assert llm.appels == 4, f"narration réutilisée malgré {surcharge}"


def test_une_decision_revue_invalide_le_cache():
    """La mémoire des décisions passées entre dans le prompt de l'avocat du
    contraire : c'est ce qui rend effective la promesse « la relecture recalibre
    les recommandations suivantes »."""
    llm = LLMSimule()
    _narration(llm, decisions=[{"option_retenue": "Option A", "review_verdict": ""}])
    assert llm.appels == 2

    # Même décision, verdict désormais posé → nouvelle rédaction attendue.
    _narration(llm, decisions=[{"option_retenue": "Option A", "review_verdict": "infirme"}])
    assert llm.appels == 4, "la narration a ignoré le verdict de la revue"


def test_un_plan_qui_change_invalide_le_cache():
    llm = LLMSimule()
    _narration(llm)
    assert llm.appels == 2

    _narration(llm, plan={**_PLAN, "nb_echeances": 6, "tranche_xof": 7_000_000})
    assert llm.appels == 4, "l'option C a été resservie avec l'ancien échéancier"


def test_un_repli_n_est_jamais_mis_en_cache():
    """Modèle en panne : le repli déterministe est servi, mais l'appel suivant
    réessaie — l'incident ne doit rien laisser en base."""
    casse = LLMSimule(casse=True)
    raisons, redaction = _narration(casse)

    assert casse.appels == 2
    assert raisons, "aucun repli servi"
    assert redaction["redige_par"] == "repli"
    assert _lignes_en_base() == [], "le repli a été enregistré et fige la panne"

    _narration(casse)
    assert casse.appels == 4, "le repli a été mis en cache et fige la panne"

    # Modèle rétabli : l'IA reprend la main immédiatement.
    llm = LLMSimule()
    _, redaction = _narration(llm)
    assert redaction["redige_par"] == "ia"


def test_la_redaction_est_persistee_et_survit_au_processus():
    """Le cache mémoire ne passait ni le redéploiement ni le second worker
    uvicorn. Une ligne en base, relisible sans le moindre état en mémoire."""
    llm = LLMSimule()
    raisons, redaction = _narration(llm)
    assert llm.appels == 2

    lignes = _lignes_en_base()
    assert len(lignes) == 1
    assert lignes[0].subject_ref == "BICICI"
    assert lignes[0].payload["raisons"] == raisons
    assert lignes[0].payload["redaction"]["argumentaire"] == redaction["argumentaire"]

    # Simulation de l'autre worker uvicorn : aucun état mémoire, même base.
    narration_store._LOCKS.clear()
    raisons2, redaction2 = _narration(llm)
    assert llm.appels == 2, "l'autre worker a repayé le modèle"
    assert (raisons2, redaction2) == (raisons, redaction)


def test_une_empreinte_perimee_laisse_une_ligne_a_purger():
    """L'invalidation est portée par le contenu : l'ancienne ligne n'est pas
    écrasée mais devient inatteignable — d'où la purge par ancienneté."""
    llm = LLMSimule()
    _narration(llm)
    _narration(llm, dossier=_dossier(enjeu_xof=999_000_000))

    assert len(_lignes_en_base()) == 2
    assert asyncio.run(narration_store.purge_anciennes(retention_jours=0)) == 2
    assert _lignes_en_base() == []


def test_sans_llm_le_repli_deterministe_tient():
    """Aucun modèle configuré : les deux parties restent servies, sans appel."""
    raisons, redaction = _narration(None)

    assert len(raisons) >= 1
    assert redaction["redige_par"] == "repli"
    # Le repli de l'échéancier cite le délai qui a SERVI au calcul.
    assert "36 j" in redaction["argumentaire"]


def test_store_if_ne_memorise_pas_un_resultat_refuse():
    """Le garde-fou du cache générique, isolé de l'arbitrage."""
    appels = {"n": 0}

    async def _compute():
        appels["n"] += 1
        return {"ok": appels["n"] > 2}

    async def _run():
        for _ in range(3):
            await ttl_cache.cached(("essai",), 900.0, _compute, store_if=lambda r: r["ok"])
        # Le 3e résultat était acceptable : il est mémorisé, plus aucun calcul.
        await ttl_cache.cached(("essai",), 900.0, _compute, store_if=lambda r: r["ok"])

    asyncio.run(_run())
    assert appels["n"] == 3
