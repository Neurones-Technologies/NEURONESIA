"""Tests du mix d'offre : classification par libellé et agrégation par famille.

Les cas de classification ne sont pas décoratifs : chacun correspond à un piège
rencontré sur les vraies données du miroir (6 675 opportunités). Les libellés
utilisés sont réels ou directement dérivés de libellés réels.
"""
from datetime import date

from modules.uc_offermix.aggregation import _stage_outcome, build_offer_mix
from modules.uc_offermix.taxonomy import FINE_TO_FAMILY, classify_family

TODAY = date(2026, 8, 5)


# ── Classification ────────────────────────────────────────────────────────────

def test_classify_priorite_ordre_du_dictionnaire():
    """La NATURE de l'affaire prime sur son OBJET, puis le spécifique sur le
    générique. Ordre : services → reseau → equipement → logiciel."""
    # Services d'abord : on vend une prestation, pas l'objet sur lequel elle porte.
    assert classify_family("Audit des 7 systèmes de vidéosurveillance") == "services"
    assert classify_family("Formation Cisco") == "services"
    assert classify_family("Etude datacenter") == "services"
    # Puis spécifique avant générique : le marché est réseau, pas « licence ».
    assert classify_family("Licence Cisco WAN") == "reseau"
    # Sans marqueur réseau/équipement, la licence reste logiciel.
    assert classify_family("Licence Fortinet + maintenance 3 ans") == "logiciel"


def test_classify_acronymes_bornes_mot_entier():
    """« lan » ne doit pas matcher « pLANification ». Sans borne, « PLAN DE
    FORMATION » (2 500 M FCFA en base) tombait en Réseau."""
    assert classify_family("PLAN DE FORMATION") == "services"
    assert classify_family("Plan de PRA/PCA") == "services"
    # Mais l'acronyme isolé doit bien matcher.
    assert classify_family("Refresh LAN") == "reseau"
    assert classify_family("Refresh WAN") == "reseau"
    # Faux positifs classiques de la recherche par sous-chaîne.
    assert classify_family("Marché Taïwan") is None
    assert classify_family("Sanction administrative") is None


def test_classify_ponctuation_et_accents():
    """La base mélange « Réseau »/« RESEAU » et colle les acronymes aux
    séparateurs (« SOC/CIRT », « LOT N°3 : F5 »)."""
    assert classify_family("Réseau") == "reseau"
    assert classify_family("RESEAU") == "reseau"
    assert classify_family("Câblage reseaux") == "reseau"
    assert classify_family("PROJET SOC/CIRT") == "logiciel"
    assert classify_family("LOT N°3 : Equipements F5") == "logiciel"
    assert classify_family("DLP/ Editeur SYMANTEC VARONIS") == "logiciel"


def test_classify_service_generique_en_dernier_recours():
    """« support »/« maintenance » seuls valent Services, mais ne doivent pas
    voler une affaire produit — cohérence avec licences_maintenance → logiciel."""
    assert classify_family("SUPPORT ET MAINTENANCE INFRA") == "services"
    assert classify_family("Contrat de maintenance serveurs Dell") == "equipement"
    assert classify_family("Licence Fortinet + maintenance 3 ans") == "logiciel"


def test_classify_inclassable_retourne_none():
    """Un libellé en nom de code ne dit pas ce qu'on vend. `None` est la bonne
    réponse — jamais une famille par défaut, qui rendrait les parts fausses."""
    for libelle in ["Projet KARANGA", "BABN", "BIA", "Import ligne 4922",
                    "Opportunité 2", "", "   ", None]:
        assert classify_family(libelle) is None, libelle


def test_fine_to_family_couvre_les_categories_du_crosssell():
    """Le pont vers les 5 catégories fines du cross-sell doit rester complet :
    une catégorie non mappée ferait diverger les deux tuiles du cockpit."""
    from modules.uc_crosssell.aggregation import CATEGORY_LABELS

    assert set(FINE_TO_FAMILY) == set(CATEGORY_LABELS)


# ── Normalisation des étapes ──────────────────────────────────────────────────

def test_stage_outcome_absorbe_le_referentiel_doublonne():
    """16 libellés d'étape en base pour ~9 étapes réelles : deux nomenclatures
    (fr numérotée / en) et des doublons par espace parasite. Comparer par
    égalité perdrait 681 affaires gagnées ('Won')."""
    assert _stage_outcome("6-Gagné") == "won"
    assert _stage_outcome("Won") == "won"
    assert _stage_outcome("7-Perdu") == "lost"
    assert _stage_outcome("7- Perdu") == "lost"      # espace parasite
    assert _stage_outcome("Lost") == "lost"
    assert _stage_outcome("9-Annulé") == "cancelled"
    assert _stage_outcome("8-Suspendu") == "open"
    assert _stage_outcome("8- Suspendu") == "open"   # espace parasite
    assert _stage_outcome("1-Qualification") == "open"
    assert _stage_outcome("1- Qualification") == "open"
    assert _stage_outcome("Qualified") == "open"
    assert _stage_outcome(None) == "open"


# ── Agrégation ────────────────────────────────────────────────────────────────

def _opp(nom, stade="Proposition", montant=1000, proba=50, deadline="2026-07-15", famille=None):
    return {
        "opportunite": nom, "stade": stade, "revenu_attendu_xof": montant,
        "probabilite_pct": proba, "deadline": deadline, "creee_le": "2026-04-07",
        **({"famille": famille} if famille else {}),
    }


def test_parts_calculees_sur_le_classe_et_couverture_exposee():
    """Le non-classé n'est pas jeté : il sort du graphe mais reste compté dans
    `coverage`. Sans ça, « Réseau 100 % » se lirait comme 100 % du pipe."""
    res = build_offer_mix([
        _opp("Refresh WAN", montant=600),        # reseau
        _opp("Projet KARANGA", montant=400),     # non classé
    ], today=TODAY)

    cov = res["coverage"]
    assert cov["nb_total"] == 2
    assert cov["nb_classe"] == 1
    assert cov["nb_non_classe"] == 1
    assert cov["couverture_montant_pct"] == 60.0   # 600 / 1000
    assert cov["montant_non_classe_xof"] == 400

    reseau = next(f for f in res["families"] if f["family"] == "reseau")
    assert reseau["part_montant_pct"] == 100.0     # 100 % du CLASSÉ, pas du pipe
    assert sum(f["montant_xof"] for f in res["families"]) == cov["montant_classe_xof"]


def test_perimetres_distincts_ouvert_et_close():
    """Les familles portent sur le pipe OUVERT, le taux de réussite sur les
    CLOSES. Une affaire gagnée ne dit plus rien du positionnement en cours."""
    res = build_offer_mix([
        _opp("Refresh WAN", stade="Proposition", montant=1000),
        _opp("Refresh LAN", stade="6-Gagné", montant=300),
        _opp("Câblage reseaux", stade="Won", montant=200),
        _opp("Switch cisco", stade="7- Perdu", montant=500),
        _opp("WAN annulé", stade="9-Annulé", montant=900),
    ], today=TODAY)

    assert res["coverage"]["nb_total"] == 1        # seule l'ouverte
    assert res["coverage"]["montant_classe_xof"] == 1000
    assert res["nb_closes"] == 3
    assert res["nb_annulees"] == 1

    reseau = next(f for f in res["families"] if f["family"] == "reseau")
    assert reseau["nb"] == 1                       # pipe ouvert
    assert reseau["nb_closes"] == 3
    assert reseau["win_rate_pct"] == 50.0          # (300+200) / 1000 en valeur


def test_famille_persistee_prime_sur_le_libelle():
    """La colonne `offer_family` du miroir évite de reclasser à chaque appel, et
    fige la famille telle qu'elle était quand la taxonomie a tourné."""
    res = build_offer_mix([_opp("BABN", famille="reseau", montant=500)], today=TODAY)
    assert res["families"][0]["family"] == "reseau"
    assert res["coverage"]["couverture_montant_pct"] == 100.0


def test_grille_trimestrielle_calendaire_et_continue():
    """La fenêtre est calendaire, pas « les N trimestres avec données » :
    juxtaposer 2020-T4 et 2026-T2 ferait lire une explosion du pipe qui n'est
    qu'un artefact d'axe."""
    res = build_offer_mix([
        _opp("Refresh WAN", deadline="2026-07-15"),
        _opp("Refresh LAN", deadline="2021-03-01"),   # très antérieure
    ], today=TODAY, nb_past_periods=2, nb_future_periods=1)

    # 2 trimestres passés + le courant (2026-T3) + 1 futur, sans trou.
    labels = [p["period"] for p in res["periods"]]
    assert labels == ["2026-T1", "2026-T2", "2026-T3", "2026-T4"]
    assert res["hors_fenetre"]["nb"] == 1                # la 2021 est hors grille
    # Rien ne se perd : périodes + hors fenêtre + sans échéance == classé.
    somme = (sum(p["montant_total_xof"] for p in res["periods"])
             + res["hors_fenetre"]["montant_xof"] + res["sans_echeance"]["montant_xof"])
    assert somme == res["coverage"]["montant_classe_xof"]


def test_echeances_passees_marquees_echu():
    """Une échéance dépassée sur une affaire ouverte n'est pas un atterrissage :
    c'est un stock à requalifier. 90 % du pipe réel est dans ce cas."""
    res = build_offer_mix([
        _opp("Refresh WAN", deadline="2025-06-01", montant=800),   # passé
        _opp("Refresh LAN", deadline="2026-09-15", montant=200),   # futur
    ], today=TODAY)

    assert res["echu"]["nb"] == 1
    assert res["echu"]["montant_xof"] == 800
    assert res["echu"]["part_montant_pct"] == 80.0
    passe = next(p for p in res["periods"] if p["period"] == "2025-T2")
    assert passe["echu"] is True
    courant = next(p for p in res["periods"] if p["courant"])
    assert courant["period"] == "2026-T3"


def test_delta_dominante_masque_sous_le_seuil_de_volume():
    """Un trimestre à 2 opportunités dont une grosse ferait basculer la part :
    le delta doit rester None plutôt que d'afficher du bruit."""
    res = build_offer_mix([
        _opp("Refresh WAN", deadline="2026-05-01"),
        _opp("Refresh LAN", deadline="2026-08-01"),
    ], today=TODAY)
    assert res["dominante"]["delta_part_pct"] is None


def test_delta_dominante_masque_si_trimestre_concentre():
    """Le volume ne suffit pas : sur le pipe réel, un trimestre de 65 affaires
    dont UNE fait 78 % du montant produisait un « -16,7 pt » qui ne mesurait que
    cette affaire. Assez d'opportunités MAIS trop concentré → pas de delta."""
    # 40 petites affaires réseau par trimestre + une énorme affaire services sur
    # le trimestre courant, qui écrase sa répartition.
    opps = []
    for i in range(40):
        opps.append(_opp(f"Refresh WAN {i}", deadline="2026-05-01", montant=10))
    for i in range(40):
        opps.append(_opp(f"Refresh LAN {i}", deadline="2026-08-01", montant=10))
    opps.append(_opp("Formation massive", deadline="2026-08-01", montant=100_000))

    res = build_offer_mix(opps, today=TODAY)
    courant = next(p for p in res["periods"] if p["courant"])
    assert courant["nb_total"] >= 30                        # volume suffisant
    assert courant["concentration_top_deal_pct"] > 50.0     # mais concentré
    assert res["dominante"]["delta_part_pct"] is None

    # Sans l'affaire hors-norme, les deux trimestres sont comparables → delta publié.
    res_sain = build_offer_mix(opps[:-1], today=TODAY)
    assert res_sain["dominante"]["delta_part_pct"] is not None


def test_sans_echeance_isole_et_non_perdu():
    """274 opportunités en base n'ont pas d'échéance : elles n'entrent dans aucun
    trimestre mais doivent rester dans le montant classé."""
    res = build_offer_mix([_opp("Refresh WAN", deadline=None, montant=700)], today=TODAY)
    assert res["sans_echeance"]["nb"] == 1
    assert res["sans_echeance"]["montant_xof"] == 700
    assert res["coverage"]["montant_classe_xof"] == 700
    assert all(p["vide"] for p in res["periods"])


def test_robustesse_entrees_degenerees():
    """Liste vide, champs None, montants nuls : aucune division par zéro."""
    vide = build_offer_mix([], today=TODAY)
    assert vide["coverage"]["couverture_montant_pct"] == 0.0
    assert vide["dominante"]["family"] is None
    assert vide["families"] == [] or all(f["nb"] == 0 for f in vide["families"])

    nones = build_offer_mix([
        {"opportunite": None, "stade": None, "revenu_attendu_xof": None,
         "probabilite_pct": None, "deadline": None, "creee_le": None},
    ], today=TODAY)
    assert nones["coverage"]["nb_total"] == 1
    assert nones["coverage"]["nb_classe"] == 0

    zero = build_offer_mix([_opp("Refresh WAN", montant=0, proba=0)], today=TODAY)
    assert zero["coverage"]["couverture_montant_pct"] == 0.0
    assert zero["coverage"]["nb_classe"] == 1

    # Date mal formée : ignorée comme une échéance absente, sans lever.
    mauvaise_date = build_offer_mix([_opp("Refresh WAN", deadline="pas-une-date")], today=TODAY)
    assert mauvaise_date["sans_echeance"]["nb"] == 1


def test_montant_pondere_utilise_la_probabilite_declaree():
    res = build_offer_mix([_opp("Refresh WAN", montant=1000, proba=40)], today=TODAY)
    reseau = next(f for f in res["families"] if f["family"] == "reseau")
    assert reseau["montant_xof"] == 1000
    assert reseau["montant_pondere_xof"] == 400


def test_historique_reel_faux_tant_que_pas_de_snapshots():
    """Drapeau lu par le front pour ne pas présenter une projection sur les
    échéances déclarées comme une évolution mesurée."""
    res = build_offer_mix([_opp("Refresh WAN")], today=TODAY)
    assert res["historique_reel"] is False
    assert res["axe_temporel"] == "echeance"
