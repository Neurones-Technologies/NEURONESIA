"""Conditions d'entrée en arbitrage — catalogue figé, activation par profil.

Ce qui est verrouillé ici :

  1. Aucune condition active laisse la file INTACTE. C'est la promesse de
     migration du réglage : déployer la fonctionnalité ne change l'écran de
     personne tant que personne n'a coché.
  2. Les conditions cochées se combinent en ET — chacune resserre la file.
  3. Un code inconnu est ignoré, jamais une erreur : un réglage périmé en base
     ne doit pas faire tomber la file.
  4. Aucune condition ne lit un champ pouvant être inconnu — un dossier sans
     profil de payeur ni signal ne fait pas tomber l'évaluation.
  5. Les KPI restent calculés sur la file ENTIÈRE ; seule la liste est
     restreinte, et ce qui est retiré est annoncé (`filtre.nb_ecartes`).
  6. `mesure.refs_par_condition` permet de retrouver l'effet de n'importe quelle
     combinaison par intersection — c'est le contrat dont dépend le compteur
     affiché pendant que l'utilisateur coche.
"""
import asyncio

import pytest

from modules.uc_arbitrage import conditions, service


def dossier(
    ref: str,
    impaye: float = 500_000_000,
    enjeu: float = 100_000_000,
    retard: int = 300,
    classe: str = "degradation",
    signal: str = "Renouvellement",
) -> dict:
    """Dossier réduit aux champs que les conditions lisent, plus ceux dont les
    KPI de `compute_file` ont besoin."""
    return {
        "subject_ref": ref,
        "impaye_xof": impaye,
        "enjeu_xof": enjeu,
        "retard_max_jours": retard,
        "signal_type": signal,
        "profil_payeur": {"classe": classe},
        "cout_report_xof_semaine": enjeu * 0.02,
    }


# Reproduit la situation réelle du miroir : sept dossiers aux profils contrastés.
FILE = [
    # Ardoise énorme, petit enjeu, très ancien, payeur stable.
    dossier("BAD", impaye=3_778_900_000, enjeu=143_000_000, retard=1403, classe="stable"),
    # Créance de plus de deux ans, client qui a cessé de payer, signal sans levier.
    dossier("PORT AUTONOME", impaye=569_700_000, enjeu=166_200_000, retard=1475,
            classe="paiements_stoppes", signal="Obsolescence"),
    # Le dossier qui coche tout.
    dossier("BICICI", impaye=529_100_000, enjeu=318_900_000, retard=502, classe="degradation"),
    # Enjeu très supérieur à l'ardoise, retard récent, payeur qui s'améliore.
    dossier("MTN CI", impaye=417_900_000, enjeu=1_273_900_000, retard=270, classe="amelioration"),
    dossier("ENI", impaye=385_900_000, enjeu=301_000_000, retard=534,
            classe="paiements_stoppes", signal="Cross-sell"),
    dossier("SOCIETE GENERALE", impaye=362_500_000, enjeu=2_244_800_000, retard=1689,
            classe="vigilance"),
    dossier("ABI", impaye=329_200_000, enjeu=600_100_000, retard=2097, classe="stable"),
]


def refs(dossiers) -> list[str]:
    return [d["subject_ref"] for d in dossiers]


# ── 1. Le réglage vide ne filtre rien ─────────────────────────────────────────


@pytest.mark.parametrize("vide", [[], None, "", {}, "impaye_superieur_enjeu"])
def test_aucune_condition_active_laisse_la_file_intacte(vide):
    """Déployer le réglage ne doit changer l'écran de personne. Toutes les formes
    de « rien de coché » — y compris une charge utile mal typée — valent socle."""
    assert refs(conditions.appliquer(FILE, vide)) == refs(FILE)


# ── 2. Chaque condition, sur des données réelles ──────────────────────────────


def test_impaye_superieur_enjeu():
    """Ne garde que les dossiers où l'on doit plus qu'on ne va rapporter."""
    assert refs(conditions.appliquer(FILE, ["impaye_superieur_enjeu"])) == [
        "BAD", "PORT AUTONOME", "BICICI", "ENI",
    ]


def test_retard_plafond_ecarte_le_contentieux():
    """Au-delà de deux ans, le dossier n'est plus arbitrable."""
    assert refs(conditions.appliquer(FILE, ["retard_plafond"])) == ["BICICI", "MTN CI", "ENI"]


def test_classe_en_mouvement_ecarte_les_payeurs_stables():
    """Un payeur stable — même très en retard — n'émet aucun signal nouveau."""
    assert refs(conditions.appliquer(FILE, ["classe_en_mouvement"])) == [
        "PORT AUTONOME", "BICICI", "ENI", "SOCIETE GENERALE",
    ]


def test_signal_renouvellement_ne_garde_que_le_levier():
    """Obsolescence et cross-sell sortent : on ne les conditionne pas."""
    assert refs(conditions.appliquer(FILE, ["signal_renouvellement"])) == [
        "BAD", "BICICI", "MTN CI", "SOCIETE GENERALE", "ABI",
    ]


# ── 3. La combinaison est un ET ───────────────────────────────────────────────


def test_les_conditions_se_combinent_en_et():
    """Chaque case cochée resserre la file — jamais l'inverse."""
    une = conditions.appliquer(FILE, ["impaye_superieur_enjeu"])
    deux = conditions.appliquer(FILE, ["impaye_superieur_enjeu", "retard_plafond"])
    trois = conditions.appliquer(FILE, ["impaye_superieur_enjeu", "retard_plafond", "signal_renouvellement"])

    assert refs(deux) == ["BICICI", "ENI"]
    assert refs(trois) == ["BICICI"]
    assert set(refs(trois)) <= set(refs(deux)) <= set(refs(une))


def test_l_ordre_des_codes_ne_change_pas_le_resultat():
    a = conditions.appliquer(FILE, ["retard_plafond", "impaye_superieur_enjeu"])
    b = conditions.appliquer(FILE, ["impaye_superieur_enjeu", "retard_plafond"])
    assert refs(a) == refs(b)


def test_toutes_les_conditions_gardent_le_dossier_archetypal():
    """BICICI coche les quatre : la file ne descend pas à zéro sur ces données."""
    assert refs(conditions.appliquer(FILE, list(conditions.codes_connus()))) == ["BICICI"]


# ── 4. Robustesse : réglage périmé, dossier incomplet ─────────────────────────


def test_un_code_inconnu_est_ignore_pas_une_erreur():
    """Condition retirée du catalogue mais restée en base : le reste s'applique."""
    assert conditions.normaliser(["retard_plafond", "condition_disparue"]) == ["retard_plafond"]
    assert conditions.inconnus(["retard_plafond", "condition_disparue"]) == ["condition_disparue"]
    assert refs(conditions.appliquer(FILE, ["retard_plafond", "condition_disparue"])) == [
        "BICICI", "MTN CI", "ENI",
    ]


def test_un_dossier_sans_profil_ni_signal_ne_fait_pas_tomber_l_evaluation():
    """Aucune condition ne suppose un champ renseigné : un dossier tronqué est
    évalué (et écarté), il ne lève pas."""
    tronque = [{"subject_ref": "TRONQUE"}]
    for code in conditions.codes_connus():
        assert conditions.appliquer(tronque, [code]) in ([], tronque)


def test_aucune_condition_ne_lit_un_champ_nullable():
    """Invariant 2 du module : les seuls champs lus sont ceux que
    `detect_client_conflicts` renseigne toujours. Une condition ajoutée sur
    `tendance_ratio` ou `jours_depuis_dernier_paiement` rouvrirait la question
    « un dossier dont l'information manque doit-il sortir de la file ? »."""
    toujours_presents = {
        "impaye_xof", "enjeu_xof", "retard_max_jours", "signal_type", "profil_payeur.classe",
    }
    for condition in conditions.CATALOGUE:
        assert set(condition.champs) <= toujours_presents, condition.code


# ── 5. Mesure : le compteur affiché pendant qu'on coche ───────────────────────


def test_la_mesure_permet_de_recalculer_toute_combinaison_par_intersection():
    """Contrat dont dépend le compteur de l'écran : l'intersection des références
    de deux conditions donne exactement le résultat du ET côté serveur."""
    mesure = conditions.mesurer(FILE, [])
    par_condition = mesure["refs_par_condition"]

    attendu = set(par_condition["impaye_superieur_enjeu"]) & set(par_condition["retard_plafond"])
    obtenu = set(refs(conditions.appliquer(FILE, ["impaye_superieur_enjeu", "retard_plafond"])))
    assert attendu == obtenu
    assert mesure["nb_total"] == len(FILE)
    assert set(mesure["refs_total"]) == set(refs(FILE))


def test_la_mesure_compte_les_dossiers_ecartes():
    mesure = conditions.mesurer(FILE, ["retard_plafond"])
    assert (mesure["nb_total"], mesure["nb_retenus"], mesure["nb_ecartes"]) == (7, 3, 4)


# ── 6. Assemblage : ce que voit l'écran ───────────────────────────────────────


@pytest.fixture
def file_simulee(monkeypatch):
    """Court-circuite le calcul CRM et le registre : ce test porte sur le filtre
    et sur les KPI, pas sur l'assemblage (couvert par
    test_arbitrage_service_parallele)."""
    async def _candidats(crm, exclude_internal=False, subject_ref=None):
        return [dict(d) for d in FILE]

    async def _decisions(status=None, subject_ref=None):
        return []

    monkeypatch.setattr(service, "compute_candidates", _candidats)
    monkeypatch.setattr(service.store, "list_decisions", _decisions)


def _file(role, actives, monkeypatch):
    async def _conditions(profil):
        assert profil == role
        return actives

    monkeypatch.setattr(service.store, "get_conditions_profil", _conditions)
    return asyncio.run(service.compute_file(object(), role=role))


def test_les_kpi_restent_calcules_sur_la_file_entiere(file_simulee, monkeypatch):
    """Un réglage d'affichage ne doit pas faire baisser l'enjeu cumulé : sinon
    deux profils ne parlent plus des mêmes chiffres, et le briefing de nuit —
    qui n'a aucun profil — dit autre chose que l'écran."""
    complet = _file("dg", [], monkeypatch)
    filtre = _file("dg", ["retard_plafond", "impaye_superieur_enjeu"], monkeypatch)

    assert refs(filtre["candidats"]) == ["BICICI", "ENI"]
    assert refs(complet["candidats"]) == refs(FILE)
    assert filtre["kpi"] == complet["kpi"]
    assert filtre["kpi"]["dossiers_ouverts"] == len(FILE)


def test_le_filtre_annonce_ce_qu_il_retire(file_simulee, monkeypatch):
    """Ce qui sort de la file est compté, jamais masqué en silence."""
    resultat = _file("dir_financier", ["retard_plafond"], monkeypatch)
    assert resultat["filtre"] == {
        "profil": "dir_financier",
        "conditions_actives": ["retard_plafond"],
        "nb_total": 7,
        "nb_retenus": 3,
        "nb_ecartes": 4,
    }


def test_sans_profil_la_file_n_est_pas_filtree(file_simulee, monkeypatch):
    """Le briefing quotidien et le job de nuit n'ont pas d'utilisateur connecté :
    ils voient la file du socle, quel que soit le réglage des profils."""
    async def _jamais_appele(profil):
        assert profil is None
        return []

    monkeypatch.setattr(service.store, "get_conditions_profil", _jamais_appele)
    resultat = asyncio.run(service.compute_file(object()))

    assert refs(resultat["candidats"]) == refs(FILE)
    assert resultat["filtre"]["nb_ecartes"] == 0
