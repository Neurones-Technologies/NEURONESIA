"""Tests du pilotage commercial (cockpit DC).

Chaque cas protège soit une DÉCISION prise face aux vraies données du miroir, soit
un piège rencontré en les regardant. Les artefacts qui ont motivé ces tests sont
cités dans les docstrings : sans eux, une régression rétablirait silencieusement un
indicateur faux mais crédible.

`TODAY` est figé partout : les pics, l'enlisement et le statut des périodes
dépendent de la date d'observation, un test qui lirait `date.today()` casserait
tout seul au changement de mois.
"""
from datetime import date

from modules.uc_commercial import statique
from modules.uc_commercial.alertes import build_alertes
from modules.uc_commercial.comptes import (
    build_acquisition,
    build_pics_activite,
    build_top_comptes,
)
from modules.uc_commercial.cycle_vie import build_cycle_vie
from modules.uc_commercial.marche import AXES_DEFAUT, build_axes_strategiques, classer_axe
from modules.uc_commercial.objectifs import build_objectifs_gap
from modules.uc_commercial.prospection import (
    MIN_CLOSES_POUR_TAUX,
    build_efficacite,
    build_indice_prospection,
)
from modules.uc_commercial.qualite_pipe import build_qualite_pipe
from modules.uc_commercial.referentiel import (
    construire_referentiel,
    index_resolution,
    normaliser,
    resoudre,
)

TODAY = date(2026, 8, 12)
M = 1_000_000


def _opp(name, *, client="ACME", client_id="acme", stage="2-Proposition", montant=50 * M,
         proba=50, commercial="Diallo", deadline="2026-12-31", creee="2025-01-15",
         close=None, famille="reseau", opp_id=None):
    return {
        "opp_id": opp_id or name.lower().replace(" ", "-"),
        "name": name,
        "client_id": client_id,
        "client": client,
        "stage": stage,
        "montant_xof": montant,
        "probabilite_pct": proba,
        "commercial": commercial,
        "deadline": deadline,
        "creee_le": creee,
        "close_le": close,
        "modifiee_le": None,
        "famille": famille,
    }


def _cpt(nom, *, ca=1_000 * M, nb=10, opp_nb=0, opp_mnt=0.0, derniere="2026-07-01",
         premiere="2019-03-01", commercial="Diallo", impaye=0.0):
    return {
        "compte": nom,
        "client_id": nom.lower().replace(" ", "_"),
        "derniere_commande": derniere,
        "premiere_commande": premiere,
        "nb_commandes": nb,
        "ca_total_xof": ca,
        "commercial": commercial,
        "nb_impayes": 1 if impaye else 0,
        "impaye_xof": impaye,
        "retard_max_jours": 30 if impaye else 0,
        "nb_opp_ouvertes": opp_nb,
        "opp_ouvertes_xof": opp_mnt,
        "hors_referentiel": False,
    }


# ── Référentiel des commerciaux ──────────────────────────────────────────────

def test_doublon_de_casse_est_une_seule_personne():
    """Cas réel : « Segui Mireille  KOUADIO » (529 lignes) et « SEGUI MIREILLE
    KOUADIO » (201) sont la même personne. Les compter séparément coupe son
    portefeuille en deux et la fait disparaître du haut du classement."""
    ref = construire_referentiel([
        {"nom": "Segui Mireille  KOUADIO", "occurrences": 529, "sources": ["opportunities"]},
        {"nom": "SEGUI MIREILLE  KOUADIO", "occurrences": 201, "sources": ["sale_orders"]},
    ])
    assert ref["totaux"]["nb_personnes"] == 1
    personne = ref["personnes"][0]
    assert personne["occurrences"] == 730
    # L'orthographe affichée est la plus fréquente, pas la première rencontrée.
    assert personne["display_name"] == "Segui Mireille  KOUADIO"
    assert ref["totaux"]["nb_doublons_orthographe"] == 1


def test_porteurs_non_nominatifs_sont_exclus_mais_traces():
    """« Administrateur » porte 1 106 opportunités et « Assistance Commerciale »
    près de la moitié du CA 2025. Les exclure du classement individuel est correct,
    les faire disparaître ne l'est pas : leur poids doit rester lisible."""
    ref = construire_referentiel([
        {"nom": "Administrateur", "occurrences": 1106, "sources": ["opportunities"]},
        {"nom": "Assistance Commerciale", "occurrences": 383, "sources": ["sale_orders"]},
        {"nom": "Ama GAYAKPA", "occurrences": 430, "sources": ["opportunities"]},
    ])
    assert ref["totaux"]["nb_personnes"] == 1
    natures = {p["display_name"]: p["nature"] for p in ref["porteurs_non_nominatifs"]}
    assert natures == {"Administrateur": "technique", "Assistance Commerciale": "collectif"}
    # Un porteur exclu est rattaché à AUCUNE identité, et c'est écrit en base.
    alias_admin = [a for a in ref["alias"] if a["alias_raw"] == "Administrateur"][0]
    assert alias_admin["salesperson_id"] is None


def test_normalisation_ne_rapproche_pas_deux_noms_voisins():
    """KOUADIO et KOUADIA peuvent être deux personnes : aucun rapprochement
    phonétique ni par distance d'édition, un faux positif fusionnerait deux
    portefeuilles sans laisser de trace."""
    assert normaliser("Ségui  KOUADIO") == normaliser("SEGUI KOUADIO")
    assert normaliser("KOUADIO") != normaliser("KOUADIA")


def test_nom_inconnu_ressort_en_nature_inconnu():
    """Un nom absent du référentiel n'est jamais écarté en silence : il reste
    comptabilisable à l'écran."""
    index = index_resolution(construire_referentiel(
        [{"nom": "Ama GAYAKPA", "occurrences": 3, "sources": ["opportunities"]}]
    ))
    assert resoudre(index, "Ama GAYAKPA")["nature"] is None
    assert resoudre(index, "Nouveau Venu")["nature"] == "inconnu"
    assert resoudre(index, "")["nature"] == "absent"


# ── Top comptes : quantité ET montant ────────────────────────────────────────

def test_lecture_divergente_entre_quantite_et_montant():
    """Exigence explicite du DC : « l'un des deux seuls ne suffit pas à qualifier
    un compte ». Un compte à beaucoup de petites commandes et un compte à une
    seule grosse doivent être signalés comme se lisant différemment selon l'axe."""
    comptes = [
        _cpt("VOLUME", ca=100 * M, nb=200),      # beaucoup de commandes, peu de CA
        _cpt("GROS TICKET", ca=5_000 * M, nb=2),  # deux commandes, gros CA
        _cpt("MOYEN", ca=800 * M, nb=40),
    ]
    res = build_top_comptes(comptes, [], today=TODAY)
    par_nom = {c["compte"]: c for c in res["comptes"]}
    assert par_nom["GROS TICKET"]["indice_montant"] > par_nom["GROS TICKET"]["indice_quantite"]
    assert par_nom["VOLUME"]["indice_quantite"] > par_nom["VOLUME"]["indice_montant"]
    assert res["totaux"]["nb_lectures_divergentes"] >= 2


def test_opportunites_echues_ne_comptent_pas_dans_le_a_venir():
    """4 276 opportunités ouvertes du miroir portent une échéance dépassée. Les
    compter comme du pipe « à venir » gonflerait le classement des comptes les
    moins bien tenus."""
    comptes = [_cpt("ACME", ca=100 * M, nb=5)]
    opps = [
        _opp("Future", deadline="2026-12-01", montant=300 * M),
        _opp("Passee", deadline="2025-01-01", montant=900 * M, opp_id="passee"),
    ]
    res = build_top_comptes(comptes, opps, today=TODAY)
    ligne = res["comptes"][0]
    assert ligne["nb_opp_a_venir"] == 1
    assert ligne["pipe_a_venir_xof"] == 300 * M
    assert ligne["nb_opp_echues"] == 1
    assert ligne["pipe_echu_xof"] == 900 * M


def test_opportunite_sans_client_id_est_rattachee_par_nom():
    """83 opportunités du miroir ont un `client_id` vide mais un nom exploitable :
    ce sont des affaires réelles, les perdre ferait disparaître du pipe."""
    comptes = [_cpt("ACME", ca=100 * M, nb=5)]
    opps = [_opp("Sans id", client="Acme", client_id="", montant=250 * M)]
    res = build_top_comptes(comptes, opps, today=TODAY)
    assert res["comptes"][0]["pipe_a_venir_xof"] == 250 * M


# ── Pics d'activité ──────────────────────────────────────────────────────────

def _serie(client, mois_montants, compte=None):
    return [
        {"client_id": client, "compte": compte or client.upper(), "mois": m,
         "nb": 1, "montant_xof": v, "commercial": "Diallo"}
        for m, v in mois_montants.items()
    ]


def test_pic_se_mesure_contre_la_mediane_du_compte():
    """Un compte qui commande 200 M quand il en fait 180 d'habitude ne fait pas un
    pic ; un compte à 40 M qui saute à 150 M, oui."""
    series = (
        _serie("gros", {"2026-01": 180 * M, "2026-02": 180 * M, "2026-03": 175 * M, "2026-07": 200 * M})
        + _serie("petit", {"2026-01": 40 * M, "2026-02": 40 * M, "2026-03": 38 * M, "2026-07": 150 * M})
    )
    res = build_pics_activite(series, today=TODAY)
    comptes_en_pic = {p["client_id"] for p in res["pics"]}
    assert comptes_en_pic == {"petit"}


def test_pic_ignore_les_comptes_sous_le_plancher_de_montant():
    """Sans plancher, un compte dont la médiane est à 800 000 FCFA alerterait à
    2 M — le bruit que le DC redoute explicitement."""
    series = _serie("micro", {
        "2026-01": 800_000, "2026-02": 700_000, "2026-03": 750_000, "2026-07": 3 * M,
    })
    assert build_pics_activite(series, today=TODAY)["pics"] == []


def test_compte_sous_trois_commandes_est_non_eligible():
    """Une « médiane » sur deux points n'a pas de sens : le compte est déclaré non
    éligible plutôt que jugé."""
    series = _serie("neuf", {"2026-01": 10 * M, "2026-07": 500 * M})
    res = build_pics_activite(series, today=TODAY)
    assert res["pics"] == []
    assert res["couverture"]["nb_comptes_eligibles"] == 0


def test_la_fenetre_observee_est_exclue_de_la_mediane():
    """Sinon un pic élève sa propre référence et se masque lui-même."""
    series = _serie("acc", {
        "2026-01": 20 * M, "2026-02": 20 * M, "2026-03": 20 * M,
        "2026-06": 200 * M, "2026-07": 200 * M, "2026-08": 200 * M,
    })
    res = build_pics_activite(series, today=TODAY)
    assert len(res["pics"]) == 3
    assert all(p["mediane_mensuelle_xof"] == 20 * M for p in res["pics"])


# ── Acquisition ──────────────────────────────────────────────────────────────

def test_nouveau_compte_est_compte_sur_sa_premiere_commande():
    comptes = [
        _cpt("ANCIEN", premiere="2019-05-01"),
        _cpt("RECENT", premiere="2026-02-10"),
        {**_cpt("PROSPECT"), "derniere_commande": None, "premiere_commande": None, "ca_total_xof": 0},
    ]
    res = build_acquisition(comptes, today=TODAY)
    assert res["annee_courante"]["nb_comptes"] == 1
    assert res["vivier"]["nb_prospects"] == 1
    assert {a["annee"] for a in res["annees"]} == {2019, 2026}


# ── Qualité du pipe ──────────────────────────────────────────────────────────

def test_echeance_depassee_nest_pas_un_defaut_de_completude():
    """Décision structurante : 4 903 des 5 030 opportunités ouvertes portent une
    échéance absente ou dépassée. Les compter comme incomplètes ferait un
    indicateur qui signale 98 % du pipe, donc aucun indicateur."""
    opps = [
        _opp("Depassee", deadline="2025-06-30", opp_id="a"),
        _opp("Sans echeance", deadline=None, opp_id="b"),
        _opp("Complete", deadline="2026-11-30", opp_id="c"),
    ]
    res = build_qualite_pipe(opps, today=TODAY)
    a_completer = {l["opp_id"] for l in res["a_completer"]}
    a_requalifier = {l["opp_id"] for l in res["a_requalifier"]}
    assert a_completer == {"b"}
    assert a_requalifier == {"a"}
    assert res["totaux"]["nb_a_completer"] == 1
    assert res["totaux"]["nb_a_requalifier"] == 1


def test_a_closer_retient_etape_finale_ou_echeance_proche():
    """Sur ce pipe, l'étape est souvent moins à jour que la date : les deux
    critères doivent être acceptés."""
    opps = [
        _opp("Negociation lointaine", stage="4-Négociation", deadline="2026-12-20", opp_id="n"),
        _opp("Proposition imminente", stage="2-Proposition", deadline="2026-08-20", opp_id="p"),
        _opp("Proposition lointaine", stage="2-Proposition", deadline="2026-12-20", opp_id="l"),
    ]
    res = build_qualite_pipe(opps, today=TODAY)
    assert {l["opp_id"] for l in res["a_closer"]} == {"n", "p"}


def test_dossier_incomplet_a_la_signature_est_prioritaire():
    opps = [_opp("Imminente incomplete", stage="4-Négociation", deadline="2026-08-25",
                 montant=0, opp_id="x")]
    res = build_qualite_pipe(opps, today=TODAY)
    assert res["a_closer"][0]["prioritaire"] is True
    assert "montant" in res["a_closer"][0]["defauts"]


def test_etape_close_est_detectee_par_motif_et_non_par_egalite():
    """Le référentiel Odoo porte 16 libellés pour ~9 étapes réelles (« 6-Gagné »
    et « Won » coexistent) : comparer par égalité perdrait 681 affaires gagnées."""
    opps = [
        _opp("G1", stage="6-Gagné", opp_id="g1"),
        _opp("G2", stage="Won", opp_id="g2"),
        _opp("P1", stage="7-Perdu", opp_id="p1"),
        _opp("O1", stage="8- Suspendu", opp_id="o1"),
    ]
    res = build_qualite_pipe(opps, today=TODAY)
    assert res["totaux"]["nb_ouvertes"] == 1


# ── Cycle de vie ─────────────────────────────────────────────────────────────

def test_dates_dimport_en_masse_sont_ecartees_du_calcul_d_age():
    """4 927 opportunités portent la date du 07/04/2026 et 1 548 celle du
    02/07/2026 : ce sont des dates d'import. Les retenir donnerait des affaires de
    quatre mois d'âge pour des dossiers ouverts depuis des années."""
    opps = [
        _opp("Import", montant=100 * M, creee="2026-04-07", opp_id="i"),
        _opp("Vraie", montant=100 * M, creee="2025-01-15", opp_id="v"),
    ]
    res = build_cycle_vie(opps, None, [], seuil_xof=30 * M, today=TODAY)
    par_id = {a["opp_id"]: a for a in res["affaires"]}
    assert par_id["i"]["age_jours"] is None
    assert par_id["i"]["enlisee"] is False
    assert par_id["v"]["age_jours"] == (TODAY - date(2025, 1, 15)).days
    assert par_id["v"]["enlisee"] is True


def test_seuil_filtre_le_stock_trace():
    opps = [
        _opp("Petite", montant=10 * M, opp_id="p"),
        _opp("Grosse", montant=45 * M, opp_id="g"),
    ]
    res = build_cycle_vie(opps, None, [], seuil_xof=30 * M, today=TODAY)
    assert res["stock"]["nb_total"] == 1
    assert res["affaires"][0]["opp_id"] == "g"


def test_deux_instantanes_ne_font_pas_un_historique():
    """Mesuré : 2 instantanés à 14 jours d'écart, 1 seule opportunité sur 9 475 a
    changé d'étape. L'écran ne doit pas laisser croire qu'un cycle de vie est
    traçable."""
    res = build_cycle_vie([_opp("A", montant=50 * M)], None,
                          ["2026-07-28", "2026-08-11"], today=TODAY)
    profondeur = res["historique_etapes"]["profondeur_reelle"]
    assert profondeur["profondeur_jours"] == 14
    assert profondeur["exploitable"] is False
    assert res["historique_etapes"]["source"] == statique.SOURCE_STATIQUE


def test_duree_de_cycle_non_exploitable_est_signalee():
    """31 affaires datées sur 841 closes, médiane à 0 jour : la couverture doit
    primer sur le chiffre."""
    opps = [_opp(f"C{i}", montant=50 * M, stage="6-Gagné", creee="2026-04-07",
                 close="2026-04-07", opp_id=f"c{i}") for i in range(10)]
    res = build_cycle_vie(opps, None, [], seuil_xof=30 * M, today=TODAY)
    assert res["duree_close"]["exploitable"] is False


# ── Objectifs et Gap ─────────────────────────────────────────────────────────

def _ca(commercial, mois, montant, nb=1):
    return {"commercial": commercial, "mois": mois, "nb": nb, "ca_xof": montant}


def _index(noms):
    return index_resolution(construire_referentiel(
        [{"nom": n, "occurrences": 10, "sources": ["sale_orders"]} for n in noms]
    ))


def test_gap_sur_gabarit_est_marque_mixte():
    """Le réalisé est mesuré, l'objectif est posé : la valeur ne doit jamais se
    présenter comme entièrement mesurée."""
    index = _index(["Diallo"])
    res = build_objectifs_gap([], [_ca("Diallo", 3, 100 * M)], [_ca("Diallo", 3, 1_000 * M)],
                              index, 2026, "trimestre", today=TODAY)
    assert res["source"] == statique.SOURCE_MIXTE
    assert res["regle_gabarit"]
    assert res["equipe"]["objectif_annuel_xof"] == round(1_000 * M * statique.COEFF_OBJECTIF_DEMO)


def test_objectifs_saisis_font_basculer_la_source_en_reel():
    index = _index(["Diallo"])
    objectifs = [{
        "id": 1, "scope": "equipe", "scope_ref": "", "kind": "ca", "period_type": "annee",
        "period_year": 2026, "period_index": 0, "target_amount_xof": 9_000 * M,
        "target_count": 0, "revision": 1, "note": "", "created_by": "dc", "created_at": None,
    }]
    res = build_objectifs_gap(objectifs, [_ca("Diallo", 3, 100 * M)], [], index, 2026, "annee", today=TODAY)
    assert res["source"] == statique.SOURCE_REELLE
    assert res["equipe"]["objectif_annuel_xof"] == 9_000 * M
    assert res["regle_gabarit"] is None


def test_periode_a_venir_naffiche_pas_de_taux_datteinte():
    """Un T4 non commencé afficherait « 0 % » et se lirait comme un échec."""
    index = _index(["Diallo"])
    res = build_objectifs_gap([], [_ca("Diallo", 3, 100 * M)], [_ca("Diallo", 3, 1_000 * M)],
                              index, 2026, "trimestre", today=TODAY)
    par_index = {p["index"]: p for p in res["periodes"]}
    assert par_index[4]["statut"] == "a_venir"
    assert par_index[4]["taux_pct"] is None
    assert par_index[3]["statut"] == "en_cours"
    assert par_index[3]["part_ecoulee_pct"] is not None
    assert par_index[1]["statut"] == "revolue"


def test_ca_non_nominatif_reste_dans_le_total_equipe():
    """« Assistance Commerciale » porte près de la moitié du CA : l'exclure du
    total ferait un tableau dont les lignes ne font jamais la somme."""
    index = _index(["Diallo", "Assistance Commerciale"])
    ca = [_ca("Diallo", 3, 100 * M), _ca("Assistance Commerciale", 3, 400 * M)]
    res = build_objectifs_gap([], ca, ca, index, 2026, "annee", today=TODAY)
    assert res["equipe"]["realise_xof"] == 500 * M
    assert res["couverture"]["realise_nominatif_xof"] == 100 * M
    assert res["couverture"]["part_nominative_pct"] == 20.0
    assert [p["display_name"] for p in res["porteurs_non_nominatifs"]] == ["Assistance Commerciale"]


def test_commercial_sans_realise_n1_a_un_objectif_absent_et_non_zero():
    """Cas réel : un commercial qui vend en 2026 sans avoir vendu en 2025 se
    verrait attribuer un objectif de 0 par la règle du gabarit. Le signaler est
    plus utile que de publier un taux d'atteinte infini."""
    index = _index(["Nouveau", "Ancien"])
    res = build_objectifs_gap(
        [], [_ca("Nouveau", 3, 200 * M), _ca("Ancien", 3, 100 * M)], [_ca("Ancien", 3, 500 * M)],
        index, 2026, "annee", today=TODAY,
    )
    nouveau = [l for l in res["commerciaux"] if l["display_name"] == "Nouveau"][0]
    assert nouveau["objectif_absent"] is True
    assert nouveau["taux_pct"] is None
    assert nouveau["motif_objectif_absent"]


def test_objectif_trimestriel_nest_pas_lineaire():
    """Un T1 structurellement creux ne doit pas se lire comme un décrochage."""
    index = _index(["Diallo"])
    res = build_objectifs_gap([], [], [_ca("Diallo", 3, 1_000 * M)], index, 2026, "trimestre", today=TODAY)
    objectifs = [p["objectif_xof"] for p in res["periodes"]]
    assert objectifs[0] < objectifs[3]
    assert abs(sum(objectifs) - res["equipe"]["objectif_annuel_xof"]) <= 4


# ── Efficacité et prospection ────────────────────────────────────────────────

def test_taux_non_significatif_nentre_pas_dans_lindice():
    """Cas réel : plusieurs porteurs affichent 100 % en valeur avec zéro affaire
    perdue, ce qui les placerait en tête d'un classement qu'ils n'ont pas gagné."""
    noms = ["Chanceux", "Aguerri"]
    index = _index(noms)
    ref = construire_referentiel([{"nom": n, "occurrences": 10, "sources": ["opportunities"]} for n in noms])
    opps = [_opp("Une seule", stage="6-Gagné", commercial="Chanceux", montant=10 * M, opp_id="u")]
    opps += [
        _opp(f"A{i}", stage="6-Gagné" if i % 2 else "7-Perdu", commercial="Aguerri",
             montant=100 * M, opp_id=f"a{i}")
        for i in range(MIN_CLOSES_POUR_TAUX + 2)
    ]
    res = build_efficacite(opps, [], index, ref, {"opportunites": 0, "commandes": 0}, 2026)
    par_nom = {l["display_name"]: l for l in res["commerciaux"]}
    assert par_nom["Chanceux"]["taux_significatif"] is False
    assert par_nom["Chanceux"]["composantes"]["transformation"] is None
    assert par_nom["Aguerri"]["taux_significatif"] is True
    assert par_nom["Aguerri"]["composantes"]["transformation"] is not None


def test_indice_prospection_est_marque_statique():
    """La donnée de flux n'existe pas : l'écran doit le dire, pas le masquer."""
    res = build_indice_prospection(2026, "trimestre")
    assert res["source"] == statique.SOURCE_STATIQUE
    assert res["raison"]
    assert len(res["lignes"]) == 4
    assert res["totaux"]["nb_opportunites"] == sum(
        m["nb_opportunites"] for m in statique.PROSPECTION_MENSUELLE_STATIQUE
    )


# ── Axes stratégiques ────────────────────────────────────────────────────────

def test_motif_court_est_cherche_comme_mot_entier():
    """Sans encadrement par des espaces, « ia » se déclencherait sur
    « spécialisation » et l'axe IA serait faux d'un facteur dix."""
    assert classer_axe("Projet de spécialisation applicative", AXES_DEFAUT) != "Intelligence artificielle"
    assert classer_axe("Mise en place d'une IA documentaire", AXES_DEFAUT) == "Intelligence artificielle"


def test_priorite_des_motifs_tranche_les_libelles_ambigus():
    """« Data center » contient « data » : sans priorité, l'axe Données capterait
    des projets d'infrastructure."""
    assert classer_axe("Acquisition d'un data center", AXES_DEFAUT) == "Infrastructure et datacenter"
    assert classer_axe("Plateforme data et reporting", AXES_DEFAUT) == "Données et décisionnel"


def test_axes_exposent_leur_taux_de_couverture():
    """Une part calculée sur 69 % du pipe ne doit pas se lire comme une part du
    pipe total."""
    opps = [
        _opp("Refresh WAN", montant=100 * M, opp_id="w"),
        _opp("Acquisition", montant=100 * M, opp_id="a"),
    ]
    res = build_axes_strategiques(opps, AXES_DEFAUT)
    assert res["coverage"]["couverture_montant_pct"] == 50.0
    assert res["coverage"]["nb_non_classe"] == 1
    assert res["axes"][0]["axe"] == "Réseau et télécom"
    assert res["axes"][0]["part_montant_pct"] == 100.0  # part du pipe CLASSÉ


# ── Alertes ──────────────────────────────────────────────────────────────────

def test_cle_dalerte_est_deterministe():
    """Un identifiant aléatoire ferait réapparaître chaque matin une alerte déjà
    écartée — le bruit que le DC redoute."""
    pics = {"pics": [{"client_id": "acme", "compte": "ACME", "commercial": "Diallo",
                      "mois": "2026-07", "montant_xof": 100 * M, "nb_commandes_mois": 2,
                      "mediane_mensuelle_xof": 20 * M, "intensite": 5.0, "nb_mois_historique": 12}]}
    a = build_alertes(pics, {"decrochages": []}, {"a_completer": [], "a_closer": [], "a_requalifier": []},
                      today=TODAY)
    b = build_alertes(pics, {"decrochages": []}, {"a_completer": [], "a_closer": [], "a_requalifier": []},
                      today=TODAY)
    assert a["alertes"][0]["alert_key"] == b["alertes"][0]["alert_key"] == "pic:acme:2026-07"


def test_compte_decroche_avec_impaye_est_critique():
    dormance = {"decrochages": [{
        "client_id": "x", "compte": "X", "commercial": "Diallo", "mois_silence": 9,
        "derniere_commande": "2025-11-01", "ca_total_xof": 500 * M, "nb_commandes": 12,
        "alerte_impaye": True, "impaye_xof": 80 * M,
    }]}
    res = build_alertes({"pics": []}, dormance, {"a_completer": [], "a_closer": [], "a_requalifier": []},
                        today=TODAY)
    alerte = res["alertes"][0]
    assert alerte["severity"] == "critique"
    assert "Direction Financière" in alerte["action"]


def test_alertes_de_dossier_sous_le_plancher_sont_ignorees():
    """Sous le seuil, une échéance dépassée est une correction de saisie, pas un
    sujet de direction commerciale."""
    qualite = {
        "a_completer": [],
        "a_closer": [],
        "a_requalifier": [
            {"opp_id": "petite", "name": "Petite", "client": "ACME", "stage": "2-Proposition",
             "montant_xof": 5 * M, "commercial": "Diallo", "jours_de_retard": 40},
            {"opp_id": "grosse", "name": "Grosse", "client": "ACME", "stage": "2-Proposition",
             "montant_xof": 500 * M, "commercial": "Diallo", "jours_de_retard": 40},
        ],
    }
    res = build_alertes({"pics": []}, {"decrochages": []}, qualite, today=TODAY,
                        montant_plancher_xof=30 * M)
    assert [a["subject_ref"] for a in res["alertes"]] == ["grosse"]


def test_volume_total_reste_visible_malgre_le_plafond():
    """Le DC a demandé à savoir combien d'alertes le système génère, pas seulement
    combien il en montre."""
    dormance = {"decrochages": [
        {"client_id": f"c{i}", "compte": f"C{i}", "commercial": "Diallo", "mois_silence": 8,
         "derniere_commande": "2025-12-01", "ca_total_xof": i * M, "nb_commandes": 3,
         "alerte_impaye": False, "impaye_xof": 0}
        for i in range(30)
    ]}
    res = build_alertes({"pics": []}, dormance, {"a_completer": [], "a_closer": [], "a_requalifier": []},
                        today=TODAY, limit=5)
    assert res["totaux"]["nb_total"] == 30
    assert len(res["alertes"]) == 5
    assert res["totaux"]["nb_affichees"] == 5
