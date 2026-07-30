"""Assemblage de la file d'arbitrage : lectures simultanées, périmètre restreint
aux débiteurs, et cache de la file.

Ce qui est verrouillé ici :

  1. Les lectures CRM indépendantes partent ensemble. Elles s'additionnaient
     (impayés → lignes de commande → portefeuille → comportements) alors que
     seule la liste des débiteurs conditionne les suivantes.
  2. Le portefeuille et les comportements de paiement ne sont demandés que pour
     les débiteurs en retard, jamais pour tout le miroir.
  3. `/file` puis `/dossier/{ref}` — l'enchaînement systématique de l'écran — ne
     calcule la file qu'UNE fois. Le filtrage par `subject_ref` se fait sur la
     file en cache, pas en relançant tout le calcul pour n'en garder qu'une ligne.
  4. Le registre de décisions n'est PAS mis en cache : une décision qu'on vient
     de prendre doit apparaître tout de suite.
"""
import asyncio

import pytest

from core.services import ttl_cache
from modules.uc_arbitrage import service


@pytest.fixture(autouse=True)
def cache_vide():
    ttl_cache._STORE.clear()
    yield
    ttl_cache._STORE.clear()


@pytest.fixture(autouse=True)
def registre(monkeypatch):
    """Registre de décisions en mémoire, appliqué à tout le module.

    `compute_file` lit les décisions ouvertes en base. Sans ce doublon, un test
    d'assemblage ouvrirait le vrai miroir SQLite — il passe sur un poste qui l'a
    déjà synchronisé et échoue en CI, qui n'en a pas. Le compteur sert au test
    qui vérifie que ce registre n'est jamais servi depuis le cache.
    """
    lectures: list[str | None] = []

    async def _list_decisions(status=None, subject_ref=None):
        lectures.append(status)
        return []

    monkeypatch.setattr(service.store, "list_decisions", _list_decisions)
    return lectures


class CRMSimule:
    """Journalise les appels et mesure le recouvrement des lectures."""

    def __init__(self, debiteurs=None, latence: float = 0.02):
        self.latence = latence
        self.appels: list[str] = []
        self.en_vol, self.max_en_vol = 0, 0
        self.clients_demandes: dict[str, list[str] | None] = {}
        self._debiteurs = debiteurs if debiteurs is not None else [
            {"client": "BICICI", "nb_factures": 3, "montant_total_xof": 42_000_000,
             "retard_max_jours": 61},
            {"client": "MTN CI", "nb_factures": 2, "montant_total_xof": 18_000_000,
             "retard_max_jours": 12},
            # À jour : ne doit produire aucun dossier ni aucune lecture.
            {"client": "PAYEUR EXEMPLAIRE", "nb_factures": 1, "montant_total_xof": 1_000,
             "retard_max_jours": 0},
            # Débiteur sans nom exploitable : écarté avant toute requête.
            {"client": "—", "nb_factures": 1, "montant_total_xof": 5_000,
             "retard_max_jours": 90},
        ]

    async def _travail(self, nom: str):
        self.appels.append(nom)
        self.en_vol += 1
        self.max_en_vol = max(self.max_en_vol, self.en_vol)
        await asyncio.sleep(self.latence)
        self.en_vol -= 1

    async def get_unpaid_exposure(self):
        await self._travail("unpaid")
        return {"top_10_debiteurs": list(self._debiteurs)}

    async def get_order_lines(self, limit: int = 20000):
        await self._travail("order_lines")
        return [
            {"client_id": "1", "client": "BICICI", "product": "Cisco Catalyst 9300",
             "subtotal_xof": 300_000_000, "date_order": "2025-02-10"},
            {"client_id": "2", "client": "MTN CI", "product": "Licence support annuel",
             "subtotal_xof": 60_000_000, "date_order": "2025-03-01"},
        ]

    async def get_client_portfolio(self, limit: int = 50, clients=None):
        await self._travail("portfolio")
        self.clients_demandes["portfolio"] = clients
        return [{"client": "BICICI", "backlog_xof": 9_000_000,
                 "reste_a_encaisser_xof": 4_000_000, "salesperson": "Awa"}]

    async def get_invoice_collection_stats(self, client_name: str = "", year=None):
        await self._travail(f"collection:{client_name}")
        return {"client": client_name, "total_factures": 12, "payees": 9,
                "taux_recouvrement_pct": 75.0, "delai_moyen_recouvrement_reel_jours": 36,
                "nb_factures_avec_date_paiement": 9, "montant_en_attente_xof": 42_000_000}

    async def get_payment_behaviour(self, client_name: str, fenetre_mois: int = 18):
        await self._travail(f"behaviour:{client_name}")
        return {"client": client_name, "delai_recent_jours": 36, "nb_paiements_recents": 4,
                "delai_ancien_jours": 20, "nb_paiements_anciens": 5,
                "dernier_paiement": "2026-06-01", "jours_depuis_dernier_paiement": 40}


def test_les_lectures_independantes_partent_ensemble():
    crm = CRMSimule()
    asyncio.run(service.compute_candidates(crm))

    # Les impayés d'abord (ils donnent la liste des débiteurs), puis tout le reste
    # simultanément : au moins portefeuille + lignes + comportements en vol.
    assert crm.appels[0] == "unpaid"
    assert crm.max_en_vol >= 3, (
        f"lectures enchaînées au lieu d'être simultanées (max {crm.max_en_vol} en vol)"
    )


def test_seuls_les_debiteurs_en_retard_sont_interroges():
    crm = CRMSimule()
    asyncio.run(service.compute_candidates(crm))

    interroges = {a.split(":", 1)[1] for a in crm.appels if a.startswith("behaviour:")}
    assert interroges == {"BICICI", "MTN CI"}, (
        "un client à jour ou sans nom a déclenché des requêtes de comportement"
    )
    # Le portefeuille est demandé pour ces seuls clients, pas pour tout le miroir.
    assert sorted(crm.clients_demandes["portfolio"]) == ["BICICI", "MTN CI"]


def test_aucun_debiteur_en_retard_ne_declenche_aucune_lecture():
    crm = CRMSimule(debiteurs=[
        {"client": "BON PAYEUR", "nb_factures": 1, "montant_total_xof": 1_000,
         "retard_max_jours": 0},
    ])
    assert asyncio.run(service.compute_candidates(crm)) == []
    assert crm.appels == ["unpaid"], "des lectures ont été lancées sans aucun dossier possible"


def test_file_puis_dossier_ne_calcule_qu_une_fois():
    """L'enchaînement de l'écran : `/file`, puis `/dossier/{ref}`."""
    crm = CRMSimule()

    async def _scenario():
        file = await service.compute_file(crm)
        ref = file["candidats"][0]["subject_ref"]
        apres_file = list(crm.appels)
        dossier = await service.compute_candidates(crm, subject_ref=ref)
        return file, dossier, apres_file, ref

    file, dossier, apres_file, ref = asyncio.run(_scenario())

    assert crm.appels == apres_file, "l'ouverture du dossier a relancé le calcul de la file"
    assert [d["subject_ref"] for d in dossier] == [ref]
    # Le dossier servi est bien celui de la file, chiffres compris.
    assert dossier[0]["enjeu_xof"] == file["candidats"][0]["enjeu_xof"]
    assert crm.appels.count("unpaid") == 1


def test_le_registre_de_decisions_n_est_pas_mis_en_cache(registre):
    """La file peut venir du cache, les décisions ouvertes jamais : elles changent
    au moment où un mandataire tranche."""
    crm = CRMSimule()

    async def _scenario():
        await service.compute_file(crm)
        await service.compute_file(crm)

    asyncio.run(_scenario())
    assert registre == ["en_cours", "en_cours"], (
        "les décisions ouvertes ont été servies depuis le cache"
    )
    assert crm.appels.count("unpaid") == 1, "la file, elle, a été recalculée"


def test_le_cache_ne_fuit_pas_entre_requetes():
    """Un appelant qui pose une clé sur un dossier servi ne doit pas corrompre la
    file rendue aux requêtes suivantes (cf. le `{**dossier}` du router)."""
    crm = CRMSimule()

    async def _scenario():
        premier = await service.compute_candidates(crm)
        premier[0]["enjeu_xof"] = -1
        premier[0]["cle_parasite"] = "ajoutée par un appelant"
        return await service.compute_candidates(crm)

    second = asyncio.run(_scenario())
    assert second[0]["enjeu_xof"] > 0
    assert "cle_parasite" not in second[0]


def test_exclude_internal_filtre_sans_recalculer():
    """Le briefing quotidien demande la file sans les entités du groupe : il
    partage le calcul de l'écran au lieu de le refaire."""
    crm = CRMSimule(debiteurs=[
        {"client": "BICICI", "nb_factures": 3, "montant_total_xof": 42_000_000,
         "retard_max_jours": 61},
    ])

    async def _scenario():
        tout = await service.compute_candidates(crm)
        externes = await service.compute_candidates(crm, exclude_internal=True)
        return tout, externes

    tout, externes = asyncio.run(_scenario())
    assert crm.appels.count("unpaid") == 1
    assert [d["subject_ref"] for d in tout] == [d["subject_ref"] for d in externes]


def test_un_comportement_indisponible_ne_fait_pas_tomber_la_file():
    """Un client dont l'historique de paiement est illisible garde son dossier,
    classé `historique_insuffisant`, au lieu de faire échouer tout l'écran."""
    crm = CRMSimule()

    async def _casse(client_name: str, fenetre_mois: int = 18):
        raise RuntimeError("miroir indisponible")

    crm.get_payment_behaviour = _casse

    candidats = asyncio.run(service.compute_candidates(crm))
    assert candidats, "la file entière est tombée pour un seul comportement illisible"
    assert all(d["profil_payeur"]["classe"] for d in candidats)
