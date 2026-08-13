"""Tests du pilotage financier (cockpit DAF).

Chaque cas protège soit une DÉCISION prise face aux vraies données du miroir, soit
un piège rencontré en les regardant. Les artefacts qui les ont motivés sont cités
dans les docstrings : sans eux, une régression rétablirait silencieusement un
indicateur faux mais crédible — et un indicateur financier faux se retrouve en
conseil d'administration.

`TODAY` est figé partout : la vigilance avant échéance, le statut d'un mois du
calendrier, la part d'exercice écoulée et l'âge d'une créance dépendent tous du
jour où on regarde. Un test qui lirait `date.today()` casserait tout seul au
changement de mois.
"""
from datetime import date

from modules.uc_daf import statique
from modules.uc_daf.budget import (
    COUVERTURE_MARGE_MIN_PCT,
    build_lignes_budgetaires,
    build_marge_brute,
    build_performance,
    build_resultat_net,
    build_top_charges,
    classer_ligne_budgetaire,
)
from modules.uc_daf.commun import part_ecoulee_exercice_pct, taux_atteinte_pct
from modules.uc_daf.formation import build_formation
from modules.uc_daf.relation_commerciale import (
    MIN_FACTURES_COMPORTEMENT,
    build_balance_agee,
    build_dpo,
    build_dso,
    build_mauvais_payeurs,
    mesurer_creances,
)
from modules.uc_daf.series import (
    MIN_REGLEMENTS_FENETRE,
    build_burn_down,
    build_marge_annuelle,
    build_serie_dso,
    build_serie_encours,
)
from modules.uc_daf.tresorerie_prev import build_atterrissage, build_vigilance

TODAY = date(2026, 8, 12)
ANNEE = 2026
M = 1_000_000


def _facture(invoice_id, *, client="ACME", client_id="acme", montant=10 * M, reste=None,
             facture_le="2026-01-10", echeance="2026-02-10", reglee_le=None,
             statut="pending", devise="XOF", annulee=False, client_connu=True):
    return {
        "invoice_id": invoice_id,
        "reference": f"FA/{invoice_id}",
        "client_id": client_id,
        "client": client,
        "client_connu": client_connu,
        "montant_xof": montant,
        "reste_du_xof": montant if reste is None else reste,
        "devise": devise,
        "date_facture": facture_le,
        "echeance": echeance,
        "statut": statut,
        "date_reglement": reglee_le,
        "annulee": annulee,
    }


def _achat(order_id, *, fournisseur="POLARIS Distribution S.A.R.L", montant=5 * M,
           d="2026-03-15", devise="XOF", dossier=None):
    return {
        "order_id": order_id,
        "reference": f"BC/{order_id}",
        "fournisseur": fournisseur,
        "fournisseur_id": "f1",
        "montant_xof": montant,
        "devise": devise,
        "date": d,
        "etat": "purchase",
        "dossier": dossier,
    }


def _dossier(ref, *, ca_def=100 * M, dep_def=60 * M, cree="2026-02-01", ca_prov=None, marge_prov=None):
    return {
        "dossier": ref,
        "client": "ACME",
        "projet": "Projet",
        "commercial": "",
        "etat": "draft",
        "cree_le": cree,
        "ca_provisoire_xof": ca_def if ca_prov is None else ca_prov,
        "ca_definitif_xof": ca_def,
        "depense_provisoire_xof": dep_def,
        "depense_definitive_xof": dep_def,
        "marge_provisoire_xof": (ca_def - dep_def) if marge_prov is None else marge_prov,
        "marge_definitive_xof": ca_def - dep_def,
        "taux_marge_definitive_pct": 0.0,
        "montant_recu_xof": 0,
        "reste_a_encaisser_xof": 0,
        "backlog_xof": 0,
        "fournisseurs_restant_xof": 0,
    }


def _socle(factures, ca_exercice=1000 * M, jours=224):
    return mesurer_creances(factures, TODAY, ca_exercice, jours)


# ── Créances : deux délais qui ne disent pas la même chose ──────────────────

def test_delai_encaissement_et_retard_ne_se_confondent_pas():
    """Le délai se compte depuis la FACTURE, le retard depuis l'ÉCHÉANCE.

    Sur le miroir, l'écart entre les deux vaut le délai contractuel accordé
    (65,9 jours de délai constaté pour 44,9 jours de retard). Les fondre ferait
    disparaître le délai accordé au client et transformerait un paiement à
    l'heure en retard de 30 jours.
    """
    factures = [_facture("1", facture_le="2026-01-01", echeance="2026-01-31", reglee_le="2026-02-10",
                         reste=0, statut="paid")]
    socle = _socle(factures)
    assert socle["delai_encaissement_moyen_jours"] == 40.0
    assert socle["retard_moyen_jours"] == 10.0


def test_taux_recouvrement_exclut_l_encours_non_echu():
    """Une créance non encore échue n'est pas un défaut de recouvrement.

    L'inclure au dénominateur ferait baisser le taux sans qu'aucune faute n'ait
    été commise — et le taux baisserait mécaniquement à chaque facture émise.
    """
    factures = [
        _facture("payee", montant=100 * M, reste=0, statut="paid", reglee_le="2026-03-01"),
        _facture("a_echoir", montant=900 * M, echeance="2026-12-31"),
    ]
    socle = _socle(factures)
    assert socle["encours_a_echoir_xof"] == 900 * M
    assert socle["taux_recouvrement_pct"] == 100.0


def test_dso_sur_encours_et_delai_constate_sont_servis_separement():
    """Les deux lectures du DSO restent deux champs distincts.

    Sur le miroir réel, elles valent 66 jours et 418 jours : l'écart EST le stock
    d'impayés anciens. Publier un seul « DSO » ferait passer un problème de
    recouvrement pour un délai de paiement, ou l'inverse.
    """
    factures = [
        _facture("payee", montant=100 * M, reste=0, statut="paid",
                 facture_le="2026-01-01", echeance="2026-01-31", reglee_le="2026-02-10"),
        _facture("vieille", montant=500 * M, facture_le="2023-01-01", echeance="2023-02-01"),
    ]
    socle = _socle(factures, ca_exercice=1000 * M, jours=224)
    dso = build_dso(factures, socle, TODAY, ANNEE)
    assert dso["delai_encaissement_moyen_jours"] == 40.0
    assert dso["dso_encours_jours"] == round(500 * M / (1000 * M) * 224)
    assert dso["ecart_lectures_jours"] > 0


def test_balance_agee_compte_le_reste_du_pas_le_montant_facture():
    """Une facture réglée à moitié ne pèse que pour sa moitié dans la balance."""
    factures = [_facture("partielle", montant=100 * M, reste=40 * M, echeance="2026-06-01")]
    balance = build_balance_agee(factures, TODAY)
    tranche = next(t for t in balance["tranches"] if t["code"] == "61_90")
    assert tranche["montant_xof"] == 40 * M
    assert balance["total_xof"] == 40 * M


# ── Mauvais payeurs ─────────────────────────────────────────────────────────

def test_comportement_non_significatif_ne_pese_pas_dans_l_indice():
    """Un retard de 200 jours sur UNE facture est un incident, pas un comportement.

    En dessous du seuil, le retard reste affiché mais son poids est reporté sur
    l'exposition présente — sinon un client à une seule facture en litige
    dominerait le classement des mauvais payeurs.
    """
    factures = [
        _facture("a", client="LENT", client_id="lent", reste=0, statut="paid",
                 echeance="2026-01-01", reglee_le="2026-07-20"),
        _facture("b", client="LENT", client_id="lent", montant=1 * M, echeance="2026-08-01"),
    ]
    payeurs = build_mauvais_payeurs(factures, TODAY, 10)
    lent = next(c for c in payeurs["clients"] if c["client"] == "LENT")
    assert lent["comportement_significatif"] is False
    assert lent["retard_moyen_regle_jours"] is not None


def test_client_a_jour_absent_du_suivi_des_mauvais_payeurs():
    """Un client sans encours ni retard n'a rien à faire dans une liste de mauvais payeurs."""
    factures = [
        _facture(str(i), client="BON", client_id="bon", reste=0, statut="paid",
                 echeance="2026-01-31", reglee_le="2026-01-20")
        for i in range(MIN_FACTURES_COMPORTEMENT)
    ]
    payeurs = build_mauvais_payeurs(factures, TODAY, 10)
    assert payeurs["clients"] == []
    assert payeurs["totaux"]["nb_clients_factures"] == 1


def test_arriere_de_plus_de_deux_ans_compte_a_part():
    """Un impayé de sept ans n'est plus un mauvais payeur, c'est une provision.

    Le miroir en porte : des retards de 1 685 et 2 653 jours figurent au
    classement. Les compter comme du recouvrement ferait espérer un cash qui
    n'arrivera pas.
    """
    factures = [_facture("vieux", client="VIEUX", client_id="vieux", montant=50 * M,
                         facture_le="2021-01-01", echeance="2021-02-01")]
    payeurs = build_mauvais_payeurs(factures, TODAY, 10)
    assert payeurs["totaux"]["nb_clients_arriere_ancien"] == 1
    assert payeurs["totaux"]["encours_arriere_ancien_xof"] == 50 * M


# ── DPO : bascule gabarit → mesuré ──────────────────────────────────────────

def test_dpo_reste_un_gabarit_tant_qu_aucune_facture_fournisseur_n_existe():
    """`supplier_invoices` est vide : le DPO est incalculable, pas approximable.

    Ce que le bloc mesure quand même — les achats ENGAGÉS — est servi à part et
    nommé comme tel : une commande passée n'est pas une dette échue.
    """
    achats = [_achat("1", montant=400 * M), _achat("2", montant=400 * M, d="2025-03-01")]
    dpo = build_dpo([], achats, [], TODAY, ANNEE)
    assert dpo["source"] == statique.SOURCE_STATIQUE
    assert dpo["raison"]
    assert dpo["base_mesuree"]["achats_engages_exercice_xof"] == 400 * M
    assert dpo["nb_factures_fournisseurs"] == 0


def test_dpo_bascule_en_mesure_des_que_les_factures_fournisseurs_arrivent():
    """La forme de la réponse ne change pas quand la donnée arrive — seul `source` change.

    C'est la raison pour laquelle le gabarit n'est pas câblé en dur dans le
    router : le jour du raccordement, aucun écran n'est à retoucher.
    """
    fournisseurs = [{
        "invoice_id": "sf1", "fournisseur_id": "f1", "fournisseur": "POLARIS",
        "montant_xof": 30 * M, "reste_du_xof": 0, "devise": "XOF",
        "date_facture": "2026-01-01", "echeance": "2026-02-01",
        "statut_paiement": "paid", "date_reglement": "2026-02-20",
    }]
    dpo = build_dpo(fournisseurs, [_achat("1")], [], TODAY, ANNEE)
    assert dpo["source"] == statique.SOURCE_REELLE
    assert dpo["dpo_jours"] == 50.0
    assert dpo["retard_moyen_jours"] == 19.0


# ── Marge brute : deux lectures mesurées ────────────────────────────────────

def test_marge_brute_exclut_les_dossiers_sans_depense_imputee():
    """Un dossier sans dépense imputée afficherait 100 % de marge.

    1 424 dossiers sur 2 408 sont dans ce cas dans le miroir. Les moyenner avec
    les autres remonterait mécaniquement le taux de marge de l'entreprise.
    """
    dossiers = [
        _dossier("impute", ca_def=100 * M, dep_def=60 * M),
        _dossier("non_impute", ca_def=100 * M, dep_def=0),
    ]
    marge = build_marge_brute(dossiers, [], [{"mois": 1, "nb_commandes": 1, "ca_xof": 200 * M}], ANNEE, TODAY)
    assert marge["ca_realise_xof"] == 100 * M
    assert marge["marge_xof"] == 40 * M
    assert marge["taux_pct"] == 40.0
    assert marge["couverture"]["nb_dossiers_imputes"] == 1
    assert marge["couverture"]["couverture_pct"] == 50.0


def test_marge_bascule_sur_les_flux_quand_l_imputation_est_trop_faible():
    """Sur l'exercice 2026 réel, 2 dossiers sur 238 portent une dépense (0,5 % du CA).

    Publier les 96,7 % de marge de ces deux dossiers comme « marge brute réalisée »
    aurait été un chiffre faux et flatteur. En dessous du seuil de couverture,
    l'indicateur bascule sur une lecture complète — CA signé moins achats engagés —
    et le dit.
    """
    dossiers = [
        _dossier("impute", ca_def=1 * M, dep_def=100_000),
        _dossier("non_impute", ca_def=999 * M, dep_def=0),
    ]
    ca = [{"mois": 1, "nb_commandes": 10, "ca_xof": 1000 * M}]
    achats = [_achat("1", montant=600 * M)]
    marge = build_marge_brute(dossiers, achats, ca, ANNEE, TODAY)
    assert marge["couverture"]["exploitable"] is False
    assert marge["couverture"]["couverture_pct"] < COUVERTURE_MARGE_MIN_PCT
    assert marge["lecture_retenue"] == "flux"
    assert marge["taux_retenu_pct"] == 40.0
    assert marge["marge_retenue_xof"] == 400 * M


def test_marge_sans_aucun_ca_ne_publie_pas_un_taux_de_zero():
    """Un exercice vide n'est pas un exercice à 0 % de marge.

    Sans ce garde-fou, la composante marge de l'indice de performance pèserait
    comme un effondrement là où il n'y a rien à mesurer.
    """
    marge = build_marge_brute([], [], [], ANNEE, TODAY)
    assert marge["taux_retenu_pct"] is None


# ── Charges et lignes budgétaires ───────────────────────────────────────────

def test_top_charges_groupe_par_fournisseur_et_cumule():
    """Le classement des charges se lit par fournisseur, avec sa concentration."""
    achats = [
        _achat("1", fournisseur="WESTCON", montant=300 * M),
        _achat("2", fournisseur="WESTCON", montant=200 * M),
        _achat("3", fournisseur="AITEK CI", montant=100 * M),
        _achat("hors_exercice", fournisseur="WESTCON", montant=900 * M, d="2025-01-01"),
    ]
    top = build_top_charges(achats, ANNEE, TODAY, limit=10)
    assert [c["fournisseur"] for c in top["charges"]] == ["WESTCON", "AITEK CI"]
    assert top["charges"][0]["montant_xof"] == 500 * M
    assert top["charges"][-1]["part_cumulee_pct"] == 100.0
    assert top["totaux"]["montant_exercice_precedent_xof"] == 900 * M
    # Réserve de périmètre : le classement n'est pas exhaustif et doit le dire.
    assert "masse salariale" in top["perimetre"].lower()
    assert top["valide_par_daf"] is True


def test_rattachement_budgetaire_suit_la_priorite_et_avoue_le_non_classe():
    """Un achat qu'aucun motif ne reconnaît tombe dans le recueil, motif `None`.

    C'est ce qui distingue « classé en frais généraux » de « pas encore classé » :
    le second est un travail d'arbitrage à faire, pas une ligne budgétaire.
    """
    assert classer_ligne_budgetaire("POLARIS Distribution S.A.R.L")[0] == "Matériel et infrastructure"
    assert classer_ligne_budgetaire("Microsoft CSP")[0] == "Licences et abonnements éditeurs"
    ligne, motif = classer_ligne_budgetaire("ENTREPRISE INCONNUE XYZ")
    assert ligne == statique.LIGNE_RECUEIL
    assert motif is None


def test_ligne_budgetaire_se_lit_contre_la_part_d_exercice_ecoulee():
    """80 % consommés en février est une alerte, la même chose en novembre ne l'est pas.

    Sans ce repère, l'écran fabrique de fausses urgences en début d'exercice et en
    masque de vraies en fin d'exercice.
    """
    budget_materiel = next(
        l["budget_annuel_xof"] for l in statique.BUDGET_LIGNES if l["ligne"] == "Matériel et infrastructure"
    )
    achats = [_achat("1", fournisseur="WESTCON", montant=round(budget_materiel * 0.9))]
    lignes = build_lignes_budgetaires(achats, ANNEE, date(2026, 2, 15))
    materiel = next(l for l in lignes["lignes"] if l["ligne"] == "Matériel et infrastructure")
    assert materiel["statut"] == "tendu"
    assert materiel["ecart_rythme_pts"] > 0
    assert lignes["source"] == statique.SOURCE_MIXTE
    assert lignes["totaux"]["part_exercice_ecoulee_pct"] == part_ecoulee_exercice_pct(ANNEE, date(2026, 2, 15))


# ── Résultat net et performance ─────────────────────────────────────────────

def test_resultat_net_proratise_les_charges_sur_les_mois_ecoules():
    """Comparer une marge à date à douze mois de charges fabriquerait une perte.

    Le résultat reste une PROJECTION : c'est le seul champ du module dont la
    valeur ne sort d'aucune mesure comptable.
    """
    # Marge volontairement supérieure à huit mois de charges : ce cas teste le
    # prorata et l'impôt, le résultat négatif a son propre test.
    dossiers = [_dossier("d1", ca_def=8000 * M, dep_def=2000 * M)]
    marge = build_marge_brute(dossiers, [], [{"mois": 1, "nb_commandes": 1, "ca_xof": 8000 * M}], ANNEE, TODAY)
    resultat = build_resultat_net(marge, ANNEE, TODAY)
    mensuel = sum(c["montant_mensuel_xof"] for c in statique.CHARGES_STRUCTURE_MENSUELLES)
    avant_impot = marge["marge_retenue_xof"] - mensuel * 8
    assert resultat["mois_ecoules"] == 8
    assert resultat["charges_structure_xof"] == mensuel * 8
    assert resultat["source"] == statique.SOURCE_MIXTE
    assert avant_impot > 0
    assert resultat["resultat_net_projete_xof"] == avant_impot - round(avant_impot * statique.TAUX_IS_PCT / 100)


def test_pas_d_impot_sur_un_resultat_negatif():
    """Un impôt prélevé sur une perte rendrait la projection absurde."""
    dossiers = [_dossier("d1", ca_def=1 * M, dep_def=500_000)]
    marge = build_marge_brute(dossiers, [], [{"mois": 1, "nb_commandes": 1, "ca_xof": 1 * M}], ANNEE, TODAY)
    resultat = build_resultat_net(marge, ANNEE, TODAY)
    assert resultat["resultat_avant_impot_xof"] < 0
    assert resultat["impot_xof"] == 0


def test_indice_de_performance_voit_la_qualite_de_l_encours():
    """La composante ajoutée après coup, et pourquoi elle existe.

    Sans elle, l'indice ressortait « au-dessus des cibles » sur des données où
    85 % de l'encours client dépasse 90 jours de retard. Un indicateur global qui
    ne voit pas le premier problème financier de l'entreprise ne sert à rien.
    """
    factures = [
        _facture("vieille", montant=850 * M, facture_le="2024-01-01", echeance="2024-02-01"),
        _facture("recente", montant=150 * M, echeance="2026-08-01"),
    ]
    socle = _socle(factures)
    dossiers = [_dossier("d1", ca_def=1000 * M, dep_def=600 * M)]
    marge = build_marge_brute(dossiers, [], [{"mois": 1, "nb_commandes": 1, "ca_xof": 1000 * M}], ANNEE, TODAY)
    lignes = build_lignes_budgetaires([], ANNEE, TODAY)
    perf = build_performance(marge, socle, lignes, ANNEE, TODAY)

    encours = next(c for c in perf["composantes"] if c["code"] == "encours")
    assert encours["valeur"] < 20  # 85 % de l'encours est en contentieux
    assert encours["taux_atteinte_pct"] < 30
    assert perf["indice_pct"] < 100


def test_composante_non_mesurable_est_ecartee_et_le_poids_renormalise():
    """Une composante sans mesure n'est pas remplacée par une valeur neutre.

    La remplacer par 100 % flatterait l'indice, par 0 % l'effondrerait : les deux
    sont des inventions. Elle est écartée, et le retour dit laquelle et pourquoi.
    """
    socle = _socle([_facture("a", montant=100 * M, reste=0, statut="paid", reglee_le="2026-02-01")])
    marge = build_marge_brute([], [], [], ANNEE, TODAY)
    lignes = build_lignes_budgetaires([], ANNEE, TODAY)
    perf = build_performance(marge, socle, lignes, ANNEE, TODAY)
    assert "Marge brute réalisée" in perf["composantes_ecartees"]
    assert perf["poids_retenu_pct"] < 100
    assert perf["indice_pct"] is not None


def test_taux_d_atteinte_borne_et_sens_inverse():
    """Le DSO est meilleur quand il baisse ; le plafond empêche une composante d'écraser les autres."""
    assert taux_atteinte_pct(30, 60, "bas") == 120.0   # deux fois mieux que la cible, borné
    assert taux_atteinte_pct(120, 60, "bas") == 50.0
    assert taux_atteinte_pct(35, 35, "haut") == 100.0
    assert taux_atteinte_pct(None, 60, "bas") is None


# ── Trésorerie prévisionnelle ───────────────────────────────────────────────

def test_vigilance_separe_l_avant_echeance_du_recouvrement():
    """Le DAF a demandé une alerte AVANT échéance : les deux listes ne se mélangent pas.

    Fondues et triées par montant, les trois relances utiles disparaîtraient sous
    huit cents impayés anciens.
    """
    factures = [
        _facture("proche", client="A", client_id="a", montant=10 * M, echeance="2026-08-20"),
        _facture("lointaine", client="B", client_id="b", montant=10 * M, echeance="2026-12-20"),
        _facture("echue", client="C", client_id="c", montant=500 * M, echeance="2026-01-20"),
    ]
    vig = build_vigilance(factures, TODAY, 30, 20)
    assert [l["invoice_id"] for l in vig["a_echoir"]] == ["proche"]
    assert [l["invoice_id"] for l in vig["echues"]] == ["echue"]
    assert vig["totaux"]["montant_a_echoir_xof"] == 10 * M


def test_risque_de_glissement_seulement_sur_un_comportement_significatif():
    """Le glissement annoncé s'appuie sur les factures réglées du client lui-même.

    Sur une seule facture réglée en retard, l'annonce serait une extrapolation —
    et une relance préventive envoyée sans motif défendable.
    """
    reglees = [
        _facture(f"r{i}", client="LENT", client_id="lent", reste=0, statut="paid",
                 echeance="2026-01-31", reglee_le="2026-03-31")
        for i in range(MIN_FACTURES_COMPORTEMENT)
    ]
    a_venir = _facture("futur", client="LENT", client_id="lent", montant=20 * M, echeance="2026-08-25")
    vig = build_vigilance(reglees + [a_venir], TODAY, 30, 20)
    ligne = next(l for l in vig["a_echoir"] if l["invoice_id"] == "futur")
    assert ligne["risque_glissement"] is True
    assert ligne["encaissement_attendu_le"] > ligne["echeance"]

    isolee = [
        _facture("r1", client="SEUL", client_id="seul", reste=0, statut="paid",
                 echeance="2026-01-31", reglee_le="2026-05-31"),
        _facture("futur2", client="SEUL", client_id="seul", montant=5 * M, echeance="2026-08-25"),
    ]
    vig2 = build_vigilance(isolee, TODAY, 30, 20)
    assert next(l for l in vig2["a_echoir"] if l["invoice_id"] == "futur2")["risque_glissement"] is False


def test_arriere_ne_se_deverse_pas_sur_le_mois_en_cours():
    """Régression : le calendrier promettait 10,8 milliards d'encaissement en août.

    Toutes les créances dont la date attendue était dépassée étaient reportées sur
    le mois courant, soit 92 % de l'encours encaissé en un mois. Elles sont
    désormais sorties du calendrier et publiées comme arriéré — aucune donnée du
    système ne permet de dater le recouvrement d'un impayé de trois ans.
    """
    factures = [
        _facture("vieille", client="A", client_id="a", montant=800 * M,
                 facture_le="2023-01-01", echeance="2023-02-01"),
        _facture("proche", client="B", client_id="b", montant=50 * M, echeance="2026-08-25"),
    ]
    att = build_atterrissage(factures, [], TODAY, ANNEE, 6)
    aout = next(m for m in att["mois"] if m["mois"] == "2026-08")
    assert aout["encaissement_prevu_xof"] == 50 * M
    assert att["arriere"]["montant_xof"] == 800 * M
    assert att["arriere"]["nb_creances"] == 1
    assert att["arriere"]["montant_plus_de_2_ans_xof"] == 800 * M


def test_calendrier_ne_melange_pas_constate_et_projete():
    """Quatre montants par mois, jamais un seul.

    Un mois révolu se lit sur le constaté, un mois à venir sur le projeté, et le
    mois en cours cumule les deux — c'est la seule case où le mois est à la fois
    entamé et inachevé.
    """
    factures = [
        _facture("payee_mars", montant=90 * M, reste=0, statut="paid",
                 facture_le="2026-02-01", echeance="2026-03-01", reglee_le="2026-03-15"),
        _facture("attendue_sept", client="B", client_id="b", montant=40 * M, echeance="2026-09-20"),
    ]
    achats = [_achat("a1", montant=30 * M, d="2026-03-10")]
    att = build_atterrissage(factures, achats, TODAY, ANNEE, 6)

    mars = next(m for m in att["mois"] if m["mois"] == "2026-03")
    assert mars["statut"] == "revolu"
    assert mars["encaissement_constate_xof"] == 90 * M
    assert mars["decaissement_constate_xof"] == 30 * M
    assert mars["decaissement_prevu_xof"] == 0

    septembre = next(m for m in att["mois"] if m["mois"] == "2026-09")
    assert septembre["statut"] == "a_venir"
    assert septembre["encaissement_constate_xof"] == 0
    assert septembre["decaissement_prevu_xof"] == att["totaux"]["run_rate_decaissement_xof"]

    # Le cumul est une VARIATION : aucun solde bancaire n'existe dans le système.
    assert any("VARIATION" in h for h in att["hypotheses"])


# ── Formation et qualité de saisie ──────────────────────────────────────────

def test_formation_priorisee_par_les_defauts_reellement_mesures():
    """Une formation qui commence par le sujet le mieux tenu perd la salle.

    L'ordre des modules suit les compteurs mesurés, pas l'ordre de la note du DAF.
    """
    controles = {
        "echeance_incoherente": {"nb_defaut": 0, "nb_total": 100},
        "reglement_non_rattache": {"nb_defaut": 0, "nb_total": 100},
        "facture_fournisseur_absente": {"nb_defaut": 100, "nb_total": 100, "nb_factures_fournisseurs": 0},
        "achat_sans_dossier": {"nb_defaut": 99, "nb_total": 100},
        "dossier_sans_depense": {"nb_defaut": 59, "nb_total": 100},
        "client_sans_secteur": {"nb_defaut": 99, "nb_total": 100},
        "document_en_devise": {"nb_defaut": 25, "nb_total": 100},
        "facture_sans_client": {"nb_defaut": 3, "nb_total": 100},
    }
    formation = build_formation(controles, TODAY)
    assert formation["modules"][0]["controle"]["gravite"] == "critique"
    assert formation["modules"][-1]["controle"]["part_defaut_pct"] <= formation["modules"][0]["controle"]["part_defaut_pct"]
    # Chaque module reste relié à l'indicateur que son défaut casse.
    assert all(m["controle"]["indicateur_casse"] for m in formation["modules"])


def test_defaut_structurel_reste_critique_meme_a_faible_taux():
    """L'absence de facture fournisseur n'est pas une négligence : c'est un trou de données.

    Elle est critique quel que soit son taux, parce qu'aucune saisie plus soignée
    ne la corrigera — il faut raccorder la synchronisation.
    """
    controles = {
        "document_en_devise": {"nb_defaut": 1, "nb_total": 1000},
        "facture_fournisseur_absente": {"nb_defaut": 1, "nb_total": 1000, "nb_factures_fournisseurs": 0},
    }
    formation = build_formation(controles, TODAY)
    structurels = [c for c in formation["controles"] if c["structurel"]]
    assert structurels
    assert all(c["gravite"] == "critique" for c in structurels)
    assert formation["source"] == statique.SOURCE_MIXTE


# ── Séries temporelles ──────────────────────────────────────────────────────

def test_encours_reconstruit_a_chaque_fin_de_mois():
    """La courbe d'encours se reconstruit sans instantané archivé.

    Une facture émise en janvier et réglée en mai est ouverte en février, mars et
    avril, puis disparaît. C'est ce qui permet de tracer 30 mois d'historique sur
    un système qui n'archive rien.
    """
    factures = [
        _facture("reglee", montant=100 * M, facture_le="2026-01-10", echeance="2026-02-10",
                 reglee_le="2026-05-20", reste=0, statut="paid"),
        _facture("ouverte", montant=50 * M, facture_le="2026-03-01", echeance="2026-04-01"),
    ]
    serie = build_serie_encours(factures, TODAY, profondeur=8)
    par_mois = {p["mois"]: p for p in serie["points"]}
    assert par_mois["2026-03"]["total_xof"] == 150 * M   # les deux sont ouvertes
    assert par_mois["2026-06"]["total_xof"] == 50 * M    # la première est réglée
    # La limite de la reconstruction est portée par le retour, pas laissée au lecteur.
    assert "règlement partiel" in serie["limite"]


def test_encours_ventile_par_anciennete_croissante():
    """Les tranches sont ORDINALES : leur ordre est le sens de l'indicateur."""
    factures = [
        _facture("vieille", montant=90 * M, facture_le="2023-01-01", echeance="2023-02-01"),
        _facture("recente", client="B", client_id="b", montant=10 * M,
                 facture_le="2026-08-01", echeance="2026-09-30"),
    ]
    serie = build_serie_encours(factures, TODAY, profondeur=2)
    dernier = serie["points"][-1]
    tranches = {t["code"]: t["montant_xof"] for t in dernier["tranches"]}
    assert tranches["90_plus"] == 90 * M
    assert tranches["non_echu"] == 10 * M
    assert [t["code"] for t in dernier["tranches"]] == ["non_echu", "0_30", "31_90", "90_plus"]


def test_dso_ne_publie_pas_un_point_sur_trop_peu_de_reglements():
    """Un DSO calculé sur deux factures est une anecdote, pas une tendance."""
    factures = [
        _facture(f"r{i}", montant=10 * M, reste=0, statut="paid",
                 facture_le="2026-01-01", echeance="2026-01-31", reglee_le="2026-03-05")
        for i in range(MIN_REGLEMENTS_FENETRE - 1)
    ]
    serie = build_serie_dso(factures, TODAY, 60, profondeur=8)
    mars = next(p for p in serie["points"] if p["mois"] == "2026-03")
    assert mars["delai_moyen_jours"] is None
    assert mars["exploitable"] is False


def test_dso_signale_les_mois_dont_la_synchronisation_est_incomplete():
    """Régression : le délai bondit à 127 jours sur des mois à zéro règlement.

    Quand seuls les règlements les plus tardifs ont été rapatriés de l'ERP, la
    moyenne monte sans que rien n'ait changé chez les clients. Ces mois sont
    signalés, tracés en pointillé, et exclus du résumé — sinon le cockpit annonce
    une dérive qui n'est qu'un retard de synchronisation.
    """
    nombreux = [
        _facture(f"n{i}", montant=10 * M, reste=0, statut="paid",
                 facture_le="2026-01-01", echeance="2026-01-31", reglee_le="2026-02-10")
        for i in range(20)
    ]
    rare = [
        _facture("tardif", montant=10 * M, reste=0, statut="paid",
                 facture_le="2025-06-01", echeance="2025-07-01", reglee_le="2026-07-15"),
    ]
    serie = build_serie_dso(nombreux + rare, TODAY, 60, profondeur=10)
    juillet = next(p for p in serie["points"] if p["mois"] == "2026-07")
    fevrier = next(p for p in serie["points"] if p["mois"] == "2026-02")
    assert juillet["synchronisation_incomplete"] is True
    assert fevrier["synchronisation_incomplete"] is False
    # Le résumé retient le dernier mois FIABLE, pas le dernier mois tracé.
    assert serie["resume"]["dernier_mois_fiable"] == fevrier["libelle"]


def test_burn_down_superpose_le_ca_pour_trancher_la_sous_consommation():
    """Une consommation d'achats basse n'est une économie que si le CA tient.

    Les trois tracés partagent une seule échelle de montants : jamais deux axes,
    qui inventeraient une corrélation absente des données.
    """
    achats = [_achat("a1", montant=100 * M, d="2026-01-15"), _achat("a2", montant=200 * M, d="2026-02-10")]
    ca = [{"mois": 1, "nb_commandes": 3, "ca_xof": 400 * M}, {"mois": 2, "nb_commandes": 4, "ca_xof": 600 * M}]
    burn = build_burn_down(achats, ca, 3600 * M, ANNEE, date(2026, 2, 28))
    assert [p["achats_cumules_xof"] for p in burn["points"]] == [100 * M, 300 * M]
    assert [p["ca_cumule_xof"] for p in burn["points"]] == [400 * M, 1000 * M]
    assert burn["points"][1]["rythme_budget_xof"] == 600 * M   # 2/12 du budget
    assert burn["points"][1]["ecart_rythme_xof"] == -300 * M
    assert burn["resume"]["taux_marge_flux_pct"] == 70.0


def test_marge_annuelle_grise_un_exercice_non_comparable():
    """Un exercice dont deux dossiers portent une dépense n'est pas comparable.

    C'est le cas de l'exercice en cours sur ce miroir : 2 dossiers imputés sur
    238. Le tracer comme les autres laisserait croire à une marge de 96 %.
    """
    dossiers = (
        [_dossier(f"a{i}", ca_def=100 * M, dep_def=60 * M, cree="2025-03-01") for i in range(10)]
        + [_dossier("b1", ca_def=1 * M, dep_def=100_000, cree="2026-02-01")]
        + [_dossier("b2", ca_def=999 * M, dep_def=0, cree="2026-02-01")]
    )
    marge = build_marge_annuelle(dossiers, TODAY, 35.0)
    par_annee = {p["annee"]: p for p in marge["points"]}
    assert par_annee[2025]["exploitable"] is True
    assert par_annee[2025]["taux_pct"] == 40.0
    assert par_annee[2026]["exploitable"] is False
    assert marge["resume"]["dernier_exercice_exploitable"] == 2025
