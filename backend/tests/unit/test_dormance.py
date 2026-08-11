"""Tests du suivi de dormance : segmentation du portefeuille par rythme de commande.

Chaque cas correspond à un piège rencontré sur les vraies données du miroir
(1 482 comptes) ou à une décision métier du Directeur Commercial qu'il faut
protéger d'une régression.

`TODAY` est figé : la segmentation dépend de la date d'observation (~10 comptes
changent de segment par mois), donc un test qui lirait `date.today()` casserait
tout seul au changement de mois.
"""
from datetime import date

from modules.uc_dormance.aggregation import (
    SEGMENT_ORDER,
    build_suivi_dormance,
)

TODAY = date(2026, 8, 31)


def _cpt(nom, derniere="2026-08-01", *, ca=1_000_000, nb=2, impaye=0.0,
         retard=0, opp_nb=0, opp_mnt=0.0, commercial="Diallo", hors_ref=False):
    return {
        "compte": nom,
        "client_id": nom.lower().replace(" ", "_"),
        "derniere_commande": derniere,
        "premiere_commande": "2019-01-01",
        "nb_commandes": nb,
        "ca_total_xof": ca,
        "commercial": commercial,
        "nb_impayes": 1 if impaye else 0,
        "impaye_xof": impaye,
        "retard_max_jours": retard,
        "nb_opp_ouvertes": opp_nb,
        "opp_ouvertes_xof": opp_mnt,
        "hors_referentiel": hors_ref,
    }


def _seg_de(res, compte):
    for s in res["segments"]:
        if any(c["compte"] == compte for c in s["comptes"]):
            return s["segment"]
    return None


# ── Bornes de segment ─────────────────────────────────────────────────────────

def test_bornes_de_segment_fermees_a_gauche():
    """Seuils validés par le DC : 6 / 12 / 24 mois. Un compte à EXACTEMENT 6 mois
    de silence est « Ralentit », pas « Actif » — sinon le seuil annoncé au DC ne
    serait pas celui appliqué."""
    cas = [
        ("2026-08-01", "actif"),      # 0 mois
        ("2026-04-01", "actif"),      # 4 mois
        ("2026-03-01", "actif"),      # 5 mois
        ("2026-02-01", "ralentit"),   # 6 mois — bascule
        ("2025-10-01", "ralentit"),   # 10 mois
        ("2025-09-01", "ralentit"),   # 11 mois
        ("2025-08-01", "dormant"),    # 12 mois — bascule
        ("2024-10-01", "dormant"),    # 22 mois
        ("2024-09-01", "dormant"),    # 23 mois
        ("2024-08-01", "perdu"),      # 24 mois — bascule
        ("2020-01-01", "perdu"),      # 79 mois
    ]
    res = build_suivi_dormance([_cpt(f"C{i}", d) for i, (d, _) in enumerate(cas)], today=TODAY)
    for i, (d, attendu) in enumerate(cas):
        assert _seg_de(res, f"C{i}") == attendu, f"{d} devrait être {attendu}"


def test_prospect_sans_commande_jamais_perdu():
    """Un compte sans commande est un PROSPECT, pas un client perdu : les deux
    demandent des actions opposées. `mois_silence` reste None — il n'a jamais
    été bruyant, il ne peut pas être silencieux."""
    res = build_suivi_dormance(
        [_cpt("Nouveau", None, ca=0, nb=0)], today=TODAY
    )
    prospect = next(s for s in res["segments"] if s["segment"] == "prospect")
    assert prospect["nb_comptes"] == 1
    assert prospect["comptes"][0]["mois_silence"] is None
    assert next(s for s in res["segments"] if s["segment"] == "perdu")["nb_comptes"] == 0
    assert res["totaux"]["nb_prospects"] == 1
    assert res["totaux"]["nb_avec_commande"] == 0


def test_ordre_des_segments_est_metier_pas_par_volume():
    """L'ordre Actif → Prospect est une progression d'ancienneté que le front
    affiche telle quelle. Un tri par volume la casserait."""
    res = build_suivi_dormance([
        _cpt("P1", None), _cpt("P2", None), _cpt("P3", None),   # prospect majoritaire
        _cpt("A", "2026-08-01"),
    ], today=TODAY)
    assert [s["segment"] for s in res["segments"]] == SEGMENT_ORDER


# ── Croisements exigés par le DC ──────────────────────────────────────────────

def test_impaye_signale_sur_compte_silencieux():
    """Décision du DC : un dormant avec impayé doit être affiché ET signifié.
    Relancer commercialement un compte en défaut de paiement est une erreur."""
    res = build_suivi_dormance([
        _cpt("Mauvais payeur", "2025-01-01", ca=500_000_000, impaye=80_000_000, retard=400),
        _cpt("Bon payeur", "2025-01-01", ca=500_000_000),
    ], today=TODAY)

    dormant = next(s for s in res["segments"] if s["segment"] == "dormant")
    assert dormant["nb_comptes"] == 2
    assert dormant["nb_avec_impaye"] == 1
    assert dormant["impaye_xof"] == 80_000_000

    assert res["dormants_avec_impaye"]["nb_comptes"] == 1
    assert res["dormants_avec_impaye"]["impaye_xof"] == 80_000_000
    # Le compte reste dans son segment ET dans la liste d'alerte : double
    # présence volontaire, l'alerte n'est pas un segment concurrent.
    fiche = res["dormants_avec_impaye"]["comptes"][0]
    assert fiche["compte"] == "Mauvais payeur"
    assert fiche["alerte_impaye"] is True
    assert fiche["retard_max_jours"] == 400


def test_compte_dormant_avec_pipe_ouvert_reste_dormant():
    """Conséquence assumée du choix « silence = commandes signées » : un compte
    qui génère des opportunités sans signer est dormant. Contre-intuitif et
    fréquent (45 comptes réels, 9 800 M de pipe) — donc exposé, pas masqué."""
    res = build_suivi_dormance([
        _cpt("Bavard sans signer", "2025-02-01", ca=300_000_000, opp_nb=12, opp_mnt=2_000_000_000),
    ], today=TODAY)
    dormant = next(s for s in res["segments"] if s["segment"] == "dormant")
    assert dormant["nb_comptes"] == 1
    assert dormant["nb_avec_opp_ouverte"] == 1
    assert dormant["pipe_ouvert_xof"] == 2_000_000_000
    assert dormant["comptes"][0]["nb_opp_ouvertes"] == 12


def test_decrochages_ne_retient_que_ralentit_et_dormant():
    """Le suivi d'état porte sur ce qui est RÉCUPÉRABLE. Un compte muet depuis
    5 ans n'est pas un décrochage, et un compte actif non plus."""
    res = build_suivi_dormance([
        _cpt("Actif", "2026-08-01", ca=9_000_000_000),
        _cpt("Ralentit", "2026-01-01", ca=8_000_000_000),
        _cpt("Dormant", "2025-01-01", ca=7_000_000_000),
        _cpt("Perdu", "2020-01-01", ca=6_000_000_000),
        _cpt("Prospect", None, ca=0, nb=0),
    ], today=TODAY)
    noms = [c["compte"] for c in res["decrochages"]]
    assert noms == ["Ralentit", "Dormant"]          # tri par CA décroissant
    assert res["totaux"]["nb_decroches"] == 2
    assert res["totaux"]["ca_a_risque_xof"] == 15_000_000_000


def test_sommeil_couvre_dormant_et_perdu_pas_le_ralentit():
    """Le « sommeil » (CA sorti du radar) commence à 12 mois. Le ralentissement
    récent reste dans le CA à risque, qui est le chiffre de pilotage."""
    res = build_suivi_dormance([
        _cpt("Ralentit", "2026-01-01", ca=1_000_000_000),
        _cpt("Dormant", "2025-01-01", ca=2_000_000_000),
        _cpt("Perdu", "2020-01-01", ca=3_000_000_000),
    ], today=TODAY)
    assert res["sommeil"]["ca_historique_xof"] == 5_000_000_000
    assert res["sommeil"]["nb_comptes"] == 2
    assert res["totaux"]["ca_a_risque_xof"] == 3_000_000_000


# ── Invariants et qualité de données ──────────────────────────────────────────

def test_totaux_reconcilies_aucun_compte_perdu_ni_double():
    res = build_suivi_dormance([
        _cpt("A", "2026-08-01", ca=100), _cpt("B", "2026-01-01", ca=200),
        _cpt("C", "2025-01-01", ca=300), _cpt("D", "2020-01-01", ca=400),
        _cpt("E", None, ca=0, nb=0),
    ], today=TODAY)
    assert sum(s["nb_comptes"] for s in res["segments"]) == res["totaux"]["nb_comptes"] == 5
    assert sum(s["ca_historique_xof"] for s in res["segments"]) == res["totaux"]["ca_historique_xof"] == 1000
    assert res["totaux"]["nb_avec_commande"] + res["totaux"]["nb_prospects"] == 5


def test_compte_hors_referentiel_conserve_et_signale():
    """101 comptes réels ont commandé sans exister dans `clients`, pour 7 961 M
    dont ORANGE BURKINA FASO (2 839 M, actif). Les perdre serait grave ; les
    taire empêcherait de faire corriger la synchronisation Odoo."""
    res = build_suivi_dormance([
        _cpt("Orphelin", "2026-08-01", ca=2_839_000_000, hors_ref=True),
        _cpt("Normal", "2026-08-01", ca=100_000_000),
    ], today=TODAY)
    assert res["totaux"]["nb_comptes"] == 2
    assert res["qualite_donnees"]["nb_hors_referentiel"] == 1
    assert res["qualite_donnees"]["ca_hors_referentiel_xof"] == 2_839_000_000
    actif = next(s for s in res["segments"] if s["segment"] == "actif")
    assert actif["nb_comptes"] == 2                  # l'orphelin est bien compté


def test_comptes_a_ca_nul_comptes_mais_signales():
    """Deux comptes techniques « Odoo Agent » portent une commande à 0 FCFA et
    entrent donc en Actif. Décision : les compter (aucun filtre silencieux) et
    les signaler comme anomalie de données."""
    res = build_suivi_dormance([
        _cpt("Odoo Agent", "2026-07-30", ca=0, nb=1),
        _cpt("Vrai client", "2026-07-30", ca=500_000_000),
    ], today=TODAY)
    actif = next(s for s in res["segments"] if s["segment"] == "actif")
    assert actif["nb_comptes"] == 2
    assert res["qualite_donnees"]["nb_comptes_ca_nul"] == 1
    # Un prospect (0 commande, 0 CA) ne doit PAS compter comme anomalie.
    res2 = build_suivi_dormance([_cpt("Prospect", None, ca=0, nb=0)], today=TODAY)
    assert res2["qualite_donnees"]["nb_comptes_ca_nul"] == 0


def test_silence_median_par_segment():
    res = build_suivi_dormance([
        _cpt("D1", "2025-08-01"),   # 12 mois
        _cpt("D2", "2025-02-01"),   # 18 mois
        _cpt("D3", "2024-09-01"),   # 23 mois
    ], today=TODAY)
    dormant = next(s for s in res["segments"] if s["segment"] == "dormant")
    assert dormant["nb_comptes"] == 3
    assert dormant["silence_median_mois"] == 18
    prospect = next(s for s in res["segments"] if s["segment"] == "prospect")
    assert prospect["silence_median_mois"] is None


def test_today_injecte_deplace_la_segmentation():
    """La segmentation GLISSE avec la date d'observation. C'est pourquoi `as_of`
    est dans la réponse et doit être affiché : sans lui, deux lectures prises à
    quelques mois d'écart semblent se contredire."""
    comptes = [_cpt("X", "2026-03-01")]
    aout = build_suivi_dormance(comptes, today=date(2026, 8, 31))
    decembre = build_suivi_dormance(comptes, today=date(2026, 12, 31))
    assert _seg_de(aout, "X") == "actif"        # 5 mois
    assert _seg_de(decembre, "X") == "ralentit"  # 9 mois
    assert aout["as_of"] == "2026-08-31"
    assert decembre["as_of"] == "2026-12-31"


def test_robustesse_entrees_degenerees():
    """Liste vide, None partout, date illisible, montants nuls : aucune
    exception, aucune division par zéro."""
    vide = build_suivi_dormance([], today=TODAY)
    assert vide["totaux"]["nb_comptes"] == 0
    assert all(s["part_nb_pct"] == 0.0 for s in vide["segments"])
    assert vide["decrochages"] == []

    nones = build_suivi_dormance([{
        "compte": None, "client_id": None, "derniere_commande": None,
        "nb_commandes": None, "ca_total_xof": None, "commercial": None,
        "nb_impayes": None, "impaye_xof": None, "retard_max_jours": None,
        "nb_opp_ouvertes": None, "opp_ouvertes_xof": None, "hors_referentiel": None,
    }], today=TODAY)
    assert nones["totaux"]["nb_comptes"] == 1
    assert nones["totaux"]["nb_prospects"] == 1

    # Date illisible : traitée comme absente → prospect, jamais une exception.
    mauvaise = build_suivi_dormance([_cpt("Bizarre", "pas-une-date")], today=TODAY)
    assert mauvaise["totaux"]["nb_prospects"] == 1

    # Date FUTURE (saisie erronée) : silence borné à 0, pas de mois négatif.
    future = build_suivi_dormance([_cpt("Futur", "2027-06-01")], today=TODAY)
    assert _seg_de(future, "Futur") == "actif"
    assert future["segments"][0]["comptes"][0]["mois_silence"] == 0


def test_note_distingue_de_la_rupture_de_rythme():
    """« Dormant » a un autre sens dans le briefing DG (rupture relative au
    rythme propre du compte). La note doit empêcher de comparer les deux."""
    res = build_suivi_dormance([_cpt("A")], today=TODAY)
    assert "commandes signées" in res["note"]
    assert "rupture" in res["note"].lower()
    assert res["seuils_mois"] == {"ralentit": 6, "dormant": 12, "perdu": 24}
