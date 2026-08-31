"""Composition du débrief : gating des faits par élément coché.

Le test central est `test_sans_composition_produit_le_briefing_historique` — il
verrouille le fait que le refactor de gating n'a rien changé pour les
installations sans préférence enregistrée. Les autres portent sur ce qui casse
en silence : une source interrogée pour rien, une source partagée oubliée, une
action du jour citant un dossier dont plus aucune puce ne parle.
"""
import pytest

from modules.uc_briefing import facts, preferences
from modules.uc_briefing.preferences import CATALOGUE, DEFAUTS
from modules.uc_briefing.service import _FACTS_BUILDERS


class FauxCRM:
    """Miroir figé, et compteur d'appels.

    Les valeurs sont choisies pour que chaque bloc produise une puce
    reconnaissable ; `appels` sert à prouver qu'une source non réclamée n'est
    jamais interrogée — une erreur de la table de dépendances est autrement
    totalement muette.
    """

    def __init__(self, **overrides):
        self.appels: list[str] = []
        self._overrides = overrides

    def _trace(self, nom):
        self.appels.append(nom)
        if nom in self._overrides:
            valeur = self._overrides[nom]
            if isinstance(valeur, Exception):
                raise valeur
            return valeur
        return None

    async def get_ytd_stats(self, year):
        self._trace("get_ytd_stats")
        return {"revenue_xof": 3_000_000_000 if year >= 2026 else 5_000_000_000,
                "orders_count": 30 if year >= 2026 else 50, "as_of": "2026-08-17"}

    async def get_account_rhythm_breaks(self):
        self._trace("get_account_rhythm_breaks")
        return {
            "comptes": [{
                "client": "MTN CI", "jours_silence": 138, "derniere_commande": "2026-04-01",
                "ca_annuel_moyen_xof": 1_000_000_000, "croise_impaye": True,
                "impaye_xof": 800_000_000, "retard_max_jours": 300,
            }],
            "dormants": [], "nb_comptes_rompus": 1, "nb_comptes_dormants": 0,
            "ca_annuel_historique_xof": 1_000_000_000, "ca_ytd_xof": 100_000_000,
            "impaye_cumule_xof": 800_000_000, "ca_annuel_historique_dormants_xof": 0.0,
        }

    async def get_margin_stats(self, year=None):
        self._trace("get_margin_stats")
        return {
            "nb_dossiers": 100, "ca_provisoire_total": 10_000_000_000,
            "ca_definitif_total": 9_000_000_000, "marge_provisoire_total": 2_000_000_000,
            "marge_definitive_total": 3_000_000_000, "perc_marge_provisoire_moyen": 20.0,
            "perc_marge_definitive_moyen": 33.0, "reste_a_encaisser": 4_000_000_000,
            "fournisseurs_restant": 6_000_000_000, "backlog_total": 1_000_000_000,
        }

    async def get_year_stats(self, year, exclude_internal=False):
        self._trace("get_year_stats")
        return {"year": year, "revenue_xof": 1_000_000_000 * (year - 2020),
                "orders_count": 10, "clients_with_orders": 5}

    async def get_invoice_collection_stats(self, client_name="", year=None):
        self._trace("get_invoice_collection_stats")
        return {
            "total_factures": 200, "payees": 150, "en_attente": 50,
            "taux_recouvrement_pct": 75.0, "montant_en_attente_xof": 2_500_000_000,
            "delai_moyen_recouvrement_reel_jours": 147,
            "retard_moyen_impayes_jours": 210, "nb_impayes_en_souffrance": 40,
        }

    async def get_revenue_by_sector(self, year=None, limit=20):
        self._trace("get_revenue_by_sector")
        return [
            {"secteur": "Banque", "ca_total_xof": 1_800_000_000, "nb_clients": 4, "nb_commandes": 12},
            {"secteur": "Télécoms", "ca_total_xof": 900_000_000, "nb_clients": 2, "nb_commandes": 6},
        ]

    async def get_monthly_revenue(self, year):
        self._trace("get_monthly_revenue")
        return [{"mois": m, "ca_xof": 400_000_000, "nb_commandes": 4} for m in range(1, 8)]

    async def get_top_clients(self, limit, year=None):
        self._trace("get_top_clients")
        return [{"client": f"CLIENT {i}", "ca_total_xof": 300_000_000} for i in range(limit)]

    async def get_unpaid_exposure(self):
        self._trace("get_unpaid_exposure")
        return {
            "exposition_totale_xof": 2_000_000_000, "nb_factures_impayees": 40,
            "retard_90j_montant_xof": 1_500_000_000,
            "top_10_debiteurs": [{"client": "BAD", "montant_total_xof": 900_000_000,
                                  "retard_max_jours": 400}],
        }

    async def get_client_retention(self, year=None):
        self._trace("get_client_retention")
        return {"annee_cible": 2026, "annee_reference": 2025, "taux_retention_pct": 36.3,
                "clients_retenus": 77, "clients_perdus_churn": 135, "taux_churn_pct": 63.7,
                "nouveaux_clients": 65, "clients_actifs_annee_ref": 212}

    async def get_supplier_intelligence(self, limit=10):
        self._trace("get_supplier_intelligence")
        return [{"name": "HDF SAS", "encours_du_xof": 1_800_000_000, "taux_dependance_pct": 16.0,
                 "cash_30j_xof": 1_800_000_000, "cash_60j_xof": 0, "cash_90j_xof": 0,
                 "retard_moyen_jours": 12.0, "dossiers_a_risque_fournisseur_unique": 2}]

    async def get_pipeline_stats(self):
        self._trace("get_pipeline_stats")
        return {"ca_potentiel_brut_xof": 20_000_000_000, "ca_potentiel_pondéré_xof": 8_000_000_000}

    async def list_opportunities(self, limit=500):
        self._trace("list_opportunities")
        return [{"opportunite": "AO Services", "client": "BAD", "stade": "Proposition",
                 "revenu_attendu_xof": 500_000_000, "probabilite_pct": 70,
                 "commercial": "KOFFI", "creee_le": "2026-01-15",
                 "deadline": "2026-09-01 00:00:00.000000"}]

    async def get_win_rate(self):
        self._trace("get_win_rate")
        return {"taux_nb_pct": 70.2, "taux_valeur_pct": 40.7}

    async def get_lost_deals(self, limit=5):
        self._trace("get_lost_deals")
        return {"nb_total": 12, "by_client": [{"client": "MTN CI", "montant_xof": 900_000_000, "nb": 5}]}

    async def get_hot_leads(self, limit=5):
        self._trace("get_hot_leads")
        return [{"opportunite": "AO Services", "client": "BAD",
                 "score_pondere_xof": 400_000_000, "stade": "Proposition"}]

    async def get_quarterly_forecast(self, year=None):
        self._trace("get_quarterly_forecast")
        return {"trimestre": "Q3 2026", "projection_fin_trimestre": {"realiste_xof": 700_000_000}}

    async def get_top_margin_dossiers(self, limit=5, metric="marge_provisoire", year=None):
        self._trace("get_top_margin_dossiers")
        return [
            {"ref": "DC/2021/0066", "client": "ORANGE", "marge_provisoire": 500_000_000, "perc_marge_prov": 56.7},
            {"ref": "DC/2022/0100", "client": "MTN", "marge_provisoire": 10_000_000, "perc_marge_prov": 2.1},
        ]

    async def get_revenue_by_salesperson(self, year=None, quarter=None):
        self._trace("get_revenue_by_salesperson")
        return [{"commercial": "KOFFI", "ca_total_xof": 1_000_000_000, "nb_commandes": 20}]

    async def get_revenue_by_product(self, year=None, limit=10):
        self._trace("get_revenue_by_product")
        return [{"produit": "FG-901G\tFortiGate", "ca_total_xof": 600_000_000, "nb_commandes": 3}]

    async def get_recent_orders(self, limit=5, year=None):
        self._trace("get_recent_orders")
        return [{"ref": "FP/2026/1", "client": "BAD", "montant_xof": 11_000_000, "date": "11/08/2026"}]


async def _arbitrage_neutre(*args, **kwargs):
    return {
        "kpi": {"dossiers_ouverts": 3, "enjeu_cumule_m_fcfa": 4539,
                "cout_report_m_fcfa_semaine": 102, "echeance_plus_proche_jours": 5,
                "revues_en_retard": 1},
        "candidats": [{"subject_ref": "DOSSIER-1", "enjeu_xof": 300_000_000,
                       "cout_report_xof_semaine": 10_000_000}],
    }


@pytest.fixture(autouse=True)
def _stub_arbitrage(monkeypatch):
    """La file d'arbitrage est un module voisin, pas une méthode du CRM."""
    monkeypatch.setattr(facts.arbitrage_service, "compute_file", _arbitrage_neutre)


SITUATION_NEUTRE = {
    "as_of": "2026-08-18",
    "client": {"nb_echues": 859, "montant_echu_xof": 9_650_000_000,
               "montant_contentieux_xof": 9_000_000_000},
    "fournisseur": {"nb_echues": 3658, "dette_echue_xof": 19_260_000_000},
}


@pytest.fixture(autouse=True)
def _stub_situation(monkeypatch):
    """La situation des factures vient de uc_daf, pas du CRM — même traitement
    que la file d'arbitrage. Le compteur prouve qu'une source non réclamée
    n'est jamais interrogée."""
    appels = []

    async def _situation_neutre():
        appels.append("situation_factures")
        return SITUATION_NEUTRE

    monkeypatch.setattr(facts.daf_situation, "situation_factures", _situation_neutre)
    return appels


# ── Non-régression ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sans_composition_produit_le_briefing_historique():
    """Aucune préférence enregistrée = tout est actif, comme avant le gating."""
    res = await facts.build_dg_facts(FauxCRM())
    assert len(res["bullets"]) == len(CATALOGUE["dg"])
    assert res["action"]
    assert res["facts"]["date_arret"]


@pytest.mark.asyncio
async def test_defauts_ne_contiennent_que_des_reponses_a_une_question():
    """Le cœur de la refonte du catalogue.

    Les défauts étaient auparavant l'inventaire de ce que le CRM savait
    agréger : les six éléments cochés du directeur commercial ne répondaient à
    AUCUNE question de la trame, et son briefing par défaut était donc
    intégralement hors sujet sans que rien ne le signale.
    """
    for role, elements in CATALOGUE.items():
        for element in elements:
            if element.defaut:
                assert element.question or element.bloc == "couverture", (
                    f"« {element.id} » ({role}) est coché par défaut sans répondre "
                    "à aucune question de la trame"
                )
            else:
                assert element.bloc == "complement", (
                    f"« {element.id} » ({role}) est décoché mais n'est pas rangé "
                    "en complément"
                )


@pytest.mark.asyncio
async def test_defauts_du_dg_produisent_une_puce_par_element():
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(DEFAUTS["dg"]))
    assert len(res["bullets"]) == len(DEFAUTS["dg"])
    # Les compléments restent hors du briefing par défaut.
    assert "retention_taux_pct" not in res["facts"]
    assert "fournisseurs_top_nom" not in res["facts"]
    assert "factures_echues_clients_nb" not in res["facts"]


@pytest.mark.asyncio
async def test_le_cockpit_garde_les_faits_dont_il_depend():
    """`DgTableauDeBord` lit `facts.ca_ytd_xof` et `facts.date_arret`.

    Réordonner le catalogue et déplacer les défauts ne doit pas les faire
    disparaître — l'écran retomberait sur le direct et afficherait un chiffre
    différent de celui des puces, pour le même indicateur et le même jour.
    """
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(DEFAUTS["dg"]))
    assert "ca_ytd_xof" in res["facts"]
    assert res["facts"]["date_arret"]


# ── Gating ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_element_decoche_retire_sa_puce_et_ses_faits():
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["ca_ytd"]))
    assert len(res["bullets"]) == 1
    assert "ca_ytd_xof" in res["facts"]
    # Le gating porte sur les faits autant que sur les puces : le cockpit lit
    # `facts` pour titrer, un fait orphelin produirait un titre sans puce.
    assert "concentration_top5_pct" not in res["facts"]


@pytest.mark.asyncio
async def test_source_non_reclamee_nest_jamais_interrogee():
    crm = FauxCRM()
    await facts.build_dg_facts(crm, facts.Composition(["ca_ytd"]))
    assert "get_top_clients" not in crm.appels
    assert "get_margin_stats" not in crm.appels
    # ca_ytd compare N et N-1 : deux appels, pas un.
    assert crm.appels.count("get_ytd_stats") == 2


@pytest.mark.asyncio
async def test_source_partagee_reste_interrogee_pour_un_seul_bloc():
    """`margins` sert la trésorerie ET la matérialisation — le piège exact de la
    table de dépendances."""
    crm = FauxCRM()
    res = await facts.build_dg_facts(crm, facts.Composition(["taux_materialisation"]))
    assert "get_margin_stats" in crm.appels
    assert len(res["bullets"]) == 1


@pytest.mark.asyncio
async def test_identifiant_inconnu_est_ignore_sans_erreur():
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["nexiste_pas", "ca_ytd"]))
    assert len(res["bullets"]) == 1


@pytest.mark.asyncio
async def test_source_en_panne_nemporte_que_son_fait():
    """`_safe` doit survivre au gather conditionnel."""
    crm = FauxCRM(get_margin_stats=RuntimeError("miroir indisponible"))

    # `year=` est passé par le bloc « marge de l'exercice », désormais coché par
    # défaut : une doublure à signature trop étroite lèverait un TypeError avant
    # le gather et laisserait les autres coroutines non attendues, ce qui teste
    # tout autre chose qu'une source en panne.
    async def _panne(year=None):
        raise RuntimeError("miroir indisponible")

    crm.get_margin_stats = _panne
    res = await facts.build_dg_facts(crm, facts.Composition(DEFAUTS["dg"]))
    assert res["bullets"]  # les autres puces sortent
    assert "position_nette_xof" not in res["facts"]


# ── Action du jour ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_action_ne_cite_pas_un_element_decoche():
    """Sans la file d'arbitrage ni le croisement, l'action ne peut pas nommer
    un dossier dont plus aucune puce ne parle."""
    res = await facts.build_dg_facts(
        FauxCRM(), facts.Composition(["rupture_rythme", "position_tresorerie"])
    )
    assert "DOSSIER-1" not in (res["action"] or "")
    assert "MTN CI" in res["action"]


@pytest.mark.asyncio
async def test_action_absente_quand_aucun_rang_nest_chiffrable():
    """Le repli cite la position nette : sans trésorerie interrogée, mieux vaut
    pas d'action qu'une action affirmant « 0 M FCFA de découvert »."""
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["ca_ytd"]))
    assert res["action"] is None


# ── Les quatre autres rôles ───────────────────────────────────────────────────

@pytest.mark.parametrize("role,builder", [
    ("dir_commercial", facts.build_dir_commercial_facts),
    ("dir_financier", facts.build_dir_financier_facts),
    ("dir_operations", facts.build_dir_operations_facts),
    ("commercial", facts.build_commercial_facts),
])
@pytest.mark.asyncio
async def test_chaque_role_gate_ses_elements(role, builder):
    complet = await builder(FauxCRM(), facts.Composition([e.id for e in CATALOGUE[role]]))
    defaut = await builder(FauxCRM(), facts.Composition(DEFAUTS[role]))
    assert len(complet["bullets"]) >= len(defaut["bullets"])
    assert len(defaut["bullets"]) >= 1


# ── Vue 360 DG (éléments décochés par défaut) ─────────────────────────────────

@pytest.mark.asyncio
async def test_pluriannuel_interroge_chaque_exercice():
    """La série 5 ans, c'est cinq appels — et rien d'autre du pool 360."""
    from datetime import datetime
    crm = FauxCRM()
    res = await facts.build_dg_facts(crm, facts.Composition(["ca_pluriannuel"]))
    assert crm.appels.count("get_year_stats") == 5
    assert "get_win_rate" not in crm.appels
    assert len(res["bullets"]) == 1
    # Le faux CRM fait croître le CA avec l'année : la meilleure est la plus récente.
    assert res["facts"]["pluriannuel_meilleure_annee"] == datetime.now().year


@pytest.mark.asyncio
async def test_mix_sectoriel_denonce_le_non_renseigne():
    """« Non renseigné » en tête n'est pas un secteur dominant : la puce doit le
    dire comme un défaut de qualification, pas comme un fait de marché."""
    crm = FauxCRM()

    async def _secteurs_non_qualifies(year=None, limit=20):
        return [{"secteur": "Non renseigné", "ca_total_xof": 2_000_000_000,
                 "nb_clients": 9, "nb_commandes": 20}]

    crm.get_revenue_by_sector = _secteurs_non_qualifies
    res = await facts.build_dg_facts(crm, facts.Composition(["mix_sectoriel"]))
    assert "qualification sectorielle" in res["bullets"][0]


@pytest.mark.asyncio
async def test_rythme_mensuel_ignore_le_mois_en_cours():
    """Le mois en cours est incomplet : le comparer à la moyenne fabriquerait un
    effondrement artificiel en début de mois."""
    from datetime import datetime
    mois_courant = datetime.now().month
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["rythme_mensuel"]))
    if mois_courant > 1:
        assert res["facts"]["mensuel_dernier_mois"] < mois_courant


@pytest.mark.asyncio
async def test_factures_echues_produit_puce_et_faits(_stub_situation):
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["factures_echues"]))
    assert len(res["bullets"]) == 1
    assert "859 factures clients" in res["bullets"][0]
    assert "3658 factures échues" in res["bullets"][0]
    for cle in ("factures_echues_clients_nb", "factures_echues_clients_xof",
                "factures_echues_clients_90j_xof", "factures_echues_fournisseurs_nb",
                "factures_echues_fournisseurs_xof"):
        assert cle in res["facts"], cle
    assert _stub_situation == ["situation_factures"]


@pytest.mark.asyncio
async def test_factures_echues_sans_fournisseur_le_dit(monkeypatch):
    """Aucune facture fournisseur synchronisée : la puce le dit, plutôt que
    d'afficher un zéro qui se lirait comme « aucune dette »."""
    async def _sans_fournisseur():
        return {**SITUATION_NEUTRE, "fournisseur": None}

    monkeypatch.setattr(facts.daf_situation, "situation_factures", _sans_fournisseur)
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["factures_echues"]))
    assert "n'est pas mesurable" in res["bullets"][0]
    assert "factures_echues_fournisseurs_nb" not in res["facts"]
    assert "factures_echues_clients_nb" in res["facts"]


@pytest.mark.asyncio
async def test_factures_echues_non_reclamees_jamais_calculees(_stub_situation):
    await facts.build_dg_facts(FauxCRM(), facts.Composition(["ca_ytd"]))
    assert _stub_situation == []


@pytest.mark.asyncio
async def test_echeances_ne_retient_que_les_opportunites_ouvertes():
    """`deadline` est renseignée sur les opportunités gagnées, perdues et
    annulées : sans filtre d'étape, la puce compterait des affaires closes."""
    facts_, bullets = {}, []
    facts._echeances(facts_, bullets, [
        {"opportunite": "Ouverte", "client": "A", "stade": "Proposition",
         "revenu_attendu_xof": 100, "deadline": "2026-09-01"},
        {"opportunite": "Gagnée", "client": "B", "stade": "6-Gagné",
         "revenu_attendu_xof": 999, "deadline": "2026-09-01"},
        {"opportunite": "Perdue", "client": "C", "stade": "Lost",
         "revenu_attendu_xof": 999, "deadline": "2026-09-02"},
    ], jours=3650)
    assert facts_["echeances_nb"] == 1
    assert "Ouverte" in bullets[0]


# ── Sources hors CRM du briefing évolutif ────────────────────────────────────
# `analyses`, `evenements` et `indicateurs` lisent la base DIRECTEMENT, comme
# `daf_situation` et `arbitrage_service` au-dessus — ils ne passent pas par le
# faux CRM. Sans ces doublures, ces tests interrogent le miroir de production :
# ils passent sur le poste du développeur et échouent partout ailleurs, et les
# assertions de comptage de puces ne mesurent plus le gating mais l'état des
# données du jour. Vérifié en déplaçant le fichier de base : sans stub, le test
# de non-régression tombe.

MOUVEMENTS_NEUTRES = {
    "depuis": "2026-08-20", "jusqu_a": "2026-08-27", "total_evenements": 3,
    "commandes_entrees": {"nb": 2, "montant_xof": 300_000_000,
                          "top": [{"ref": "FP/2026/1", "tiers": "CIE",
                                   "montant_xof": 200_000_000, "date": "2026-08-21"}]},
    "factures_emises": {"nb": 1, "montant_xof": 80_000_000, "top": []},
    "factures_reglees": {"nb": 0, "montant_xof": 0, "top": []},
    "achats_engages": {"nb": 0, "montant_xof": 0, "top": []},
    "opportunites_retouchees": {"nb": 0, "montant_xof": 0, "top": []},
    "changements_etape": {"mesurable": True, "nb": 1, "montant_xof": 50_000_000,
                          "nb_entrees_pipe": 0, "montant_entrees_xof": 0,
                          "depuis_snapshot": "2026-08-20", "jusqu_a_snapshot": "2026-08-27",
                          "top": [{"opportunite": "TMA", "client": "SGCI",
                                   "revenu_attendu_xof": 50_000_000,
                                   "de": "1-Qualification", "vers": "4-Négociation"}]},
}

HYGIENE_NEUTRE = {
    "seuil_jours": 15,
    "a_relancer": {"nb": 3, "montant_xof": 900_000_000,
                   "top": [{"opportunite": "Refresh WAN", "client": "MOOV", "stade": "2-Montage",
                            "revenu_attendu_xof": 500_000_000, "jours_silence": 40,
                            "deadline": "2026-12-31"}]},
    "a_assainir": {"nb": 3015, "montant_xof": 107_881_000_000, "top": []},
    "sans_echeance": {"nb": 225, "montant_xof": 13_089_000_000, "top": []},
    "reserve": "mesure l'absence de modification",
}

# Les cinq tranches PARTITIONNENT l'encours ; le contentieux est un
# sous-ensemble transversal, à part. La doublure reproduit cette structure — une
# doublure qui dérive de la vraie fonction ne teste plus rien, et c'est
# exactement ce qu'a rattrapé le passage de `contentieux` hors des tranches.
BALANCE_NEUTRE = {
    "mesurable": True, "as_of": "2026-08-27",
    "tranches": {
        "a_echoir": {"nb": 3, "montant_xof": 78_000_000},
        "j0_30": {"nb": 15, "montant_xof": 335_000_000},
        "j30_60": {"nb": 26, "montant_xof": 368_000_000},
        "j60_90": {"nb": 28, "montant_xof": 532_000_000},
        "j90_plus": {"nb": 775, "montant_xof": 9_862_000_000},
    },
    "nb_total": 847, "montant_total_xof": 11_175_000_000,
    "contentieux": {"seuil_jours": 90, "nb": 775,
                    "montant_xof": 9_862_000_000, "part_pct": 88.3},
    "intragroupe": {"nb": 1, "montant_xof": 0},
    "reserve": "43 % des factures portent une échéance égale à leur date d'émission",
}

RELANCES_NEUTRES = {
    "mesurable": True, "retard_min_jours": 30, "nb_clients": 289,
    "montant_xof": 10_762_000_000,
    "top": [{"client": "BAD", "nb_factures": 24, "montant_xof": 2_304_000_000,
             "retard_max_jours": 1413, "intragroupe": False}],
}

DSO_NEUTRE = {
    "mesurable": True, "fenetre_mois": 12, "dso_jours": 112.3, "nb_factures": 179,
    "dso_precedent_jours": 70.3, "nb_factures_precedent": 214, "ecart_jours": 42.0,
    "robuste": True,
}

DERIVE_NEUTRE = {
    "mesurable": True, "seuil_consommation_pct": 90, "nb": 654,
    "depense_engagee_xof": 13_416_000_000,
    "top": [{"ref": "DC/2024/0046", "client": "SGCI", "consommation_pct": 126.0,
             "marge_prevue_pct": 17.8, "marge_constatee_pct": 6.0,
             "ca_provisoire_xof": 0, "depense_provisoire_xof": 0,
             "ca_definitif_xof": 0, "depense_definitive_xof": 0}],
    "reserve": "la dérive se mesure sur la dépense du dossier",
}

SOUS_TRAITANCE_NEUTRE = {
    "mesurable": True, "nb_dossiers": 972, "engagement_xof": 17_133_000_000,
    "couverture_pct": 71.3, "nb_achats_orphelins": 613, "nb_engagement_depasse_ca": 60,
    "top": [{"ref": "DC/2024/0232", "client": "BAD", "nb_achats": 12,
             "engagement_xof": 663_000_000, "ca_reference_xof": 1_810_000_000,
             "base_ca": "définitif", "marge_provisoire_pct": 12.0,
             "poids_sur_ca_pct": 36.6, "engagement_depasse_ca": False}],
    "reserve": "le rattachement achat → dossier repose sur `dossier_id`",
}

VISIBILITE_NEUTRE = {
    "mesurable": True, "backlog_xof": 9_175_000_000,
    "facture_mensuel_moyen_xof": 414_000_000, "nb_factures_fenetre": 61,
    "fenetre_mois": 3, "mois_visibilite": 22.2,
}

BTB_NEUTRE = {
    "mesurable": True, "fenetre_mois": 12, "commande_xof": 10_263_000_000,
    "facture_xof": 8_422_000_000, "ratio": 1.22,
    "reserve": "commandé et facturé sont tous deux TTC",
}


# Valeurs par indicateur, choisies pour que chaque puce soit reconnaissable et
# que les deltas ne soient jamais nuls — un delta à zéro s'écrit « stable » et
# masquerait une puce qui ne sait pas se suffixer.
_VALEURS_INDICATEURS = {
    "ca_commande_mois": 500_000_000, "ca_commande_ytd": 6_128_000_000,
    "nb_commandes_ytd": 263, "nb_opportunites_ouvertes": 3969,
    "ca_facture_mois": 300_000_000, "ca_facture_ytd": 3_358_000_000,
    "encaissements_mois": 120_000_000, "encaissements_ytd": 1_466_000_000,
    "backlog": 9_175_000_000, "reste_a_encaisser": 9_134_000_000,
    "impayes_echus": 10_909_000_000, "impayes_echus_90j": 9_546_000_000,
    "pipe_brut": 131_936_000_000, "pipe_actif_brut": 10_965_000_000,
    "pipe_actif_pondere": 2_907_000_000, "achats_engages_ytd": 3_159_000_000,
}


async def _delta_neutre(cles, as_of=None):
    """Historisation en état de marche : une valeur et trois variations par clé.

    La doublure d'origine rendait `{}`, ce qui décrivait une installation où le
    job de nuit n'a jamais tourné — un cas réel, mais pas le cas nominal. Deux
    éléments du catalogue sont FAITS d'indicateurs (le CA commandé du directeur
    commercial, le CA facturé de la DAF) : avec un dictionnaire vide, ils ne
    produisaient aucune puce et paraissaient non branchés au test de gating,
    alors qu'ils se comportaient correctement.
    """
    return {
        cle: {
            "cle": cle, "libelle": cle, "unite": "nb" if cle.startswith("nb_") else "xof",
            "nature": "flux", "valeur": _VALEURS_INDICATEURS.get(cle, 1_000_000_000),
            "reserve": "",
            "j1": 5_000_000, "j1_depuis": "2026-08-26", "j1_jours": 1,
            "semaine": 20_000_000, "semaine_depuis": "2026-08-20", "semaine_jours": 7,
            "mois": 80_000_000, "mois_depuis": "2026-07-28", "mois_jours": 30,
        }
        for cle in cles
    }


def poser_doublures(monkeypatch) -> dict:
    """Installe les doublures et rend les fonctions D'ORIGINE.

    Extrait de la fixture pour être réutilisable par `test_briefing_preferences`,
    dont le test de gating construit les faits de chaque rôle et tombe sinon sur
    la base de production. Les fixtures `autouse` sont propres à leur module :
    sans cette fonction, chaque fichier de test recopierait les doublures et
    elles divergeraient l'une après l'autre.
    """
    originales = {
        "balance_agee": facts.analyses.balance_agee,
        "relances_du_jour": facts.analyses.relances_du_jour,
        "dso_glissant": facts.analyses.dso_glissant,
        "mouvements": facts.evenements.mouvements,
        "hygiene_pipe": facts.evenements.hygiene_pipe,
    }

    async def _rendre(valeur):
        return valeur

    monkeypatch.setattr(facts.evenements, "mouvements",
                        lambda *a, **k: _rendre(MOUVEMENTS_NEUTRES))
    monkeypatch.setattr(facts.evenements, "hygiene_pipe",
                        lambda *a, **k: _rendre(HYGIENE_NEUTRE))
    monkeypatch.setattr(facts.analyses, "balance_agee",
                        lambda *a, **k: _rendre(BALANCE_NEUTRE))
    monkeypatch.setattr(facts.analyses, "relances_du_jour",
                        lambda *a, **k: _rendre(RELANCES_NEUTRES))
    monkeypatch.setattr(facts.analyses, "dso_glissant",
                        lambda *a, **k: _rendre(DSO_NEUTRE))
    monkeypatch.setattr(facts.analyses, "derive_budgetaire",
                        lambda *a, **k: _rendre(DERIVE_NEUTRE))
    monkeypatch.setattr(facts.analyses, "sous_traitance_par_dossier",
                        lambda *a, **k: _rendre(SOUS_TRAITANCE_NEUTRE))
    monkeypatch.setattr(facts.analyses, "visibilite_carnet",
                        lambda *a, **k: _rendre(VISIBILITE_NEUTRE))
    monkeypatch.setattr(facts.analyses, "book_to_bill",
                        lambda *a, **k: _rendre(BTB_NEUTRE))

    monkeypatch.setattr(facts.indicateurs, "delta", _delta_neutre)
    return originales


@pytest.fixture(autouse=True)
def _stub_sources_evolutives(monkeypatch):
    """Rend hermétiques les sources qui lisent la base sans passer par le CRM."""
    return poser_doublures(monkeypatch)


# ── Non-régression du briefing évolutif ──────────────────────────────────────

@pytest.mark.asyncio
async def test_delta_absent_degrade_les_suffixes_sans_vider_le_briefing(monkeypatch):
    """Sans historisation, les puces perdent leur variation, pas leur contenu.

    Deux éléments font exception et disparaissent : le CA commandé et le CA
    facturé sont FAITS d'indicateurs. Une puce annonçant « 0 M FCFA commandés »
    parce que rien n'a été historisé vaudrait moins que son absence — c'est un
    silence délibéré, pas une perte.
    """
    async def _aucun(cles, as_of=None):
        return {}
    monkeypatch.setattr(facts.indicateurs, "delta", _aucun)

    res = await facts.build_dir_financier_facts(FauxCRM())
    attendu = len(CATALOGUE["dir_financier"]) - 1      # ca_facture_periode se tait
    assert len(res["bullets"]) == attendu
    assert res["bullets"]
    assert not any("vs hier" in b for b in res["bullets"])


@pytest.mark.asyncio
async def test_delta_en_panne_ne_fait_pas_echouer_le_briefing(monkeypatch):
    """Une historisation qui lève doit coûter les suffixes, pas la section."""
    async def _explose(cles, as_of=None):
        raise RuntimeError("indicator_snapshots inaccessible")
    monkeypatch.setattr(facts.indicateurs, "delta", _explose)

    res = await facts.build_dir_financier_facts(FauxCRM())
    assert len(res["bullets"]) == len(CATALOGUE["dir_financier"]) - 1


@pytest.mark.asyncio
async def test_delta_present_suffixe_la_puce(monkeypatch):
    async def _delta(cles, as_of=None):
        return {"impayes_echus": {
            "cle": "impayes_echus", "libelle": "Impayés", "unite": "xof",
            "nature": "stock", "valeur": 10_000_000_000, "reserve": "",
            "j1": 250_000_000, "j1_depuis": "2026-08-26", "j1_jours": 1,
            "semaine": None, "semaine_depuis": None, "semaine_jours": None,
            "mois": None, "mois_depuis": None, "mois_jours": None,
        }}
    monkeypatch.setattr(facts.indicateurs, "delta", _delta)

    res = await facts.build_dir_financier_facts(
        FauxCRM(), facts.Composition(["exposition_impayes"])
    )
    # L'exposition est citée à l'horizon « semaine », non renseigné ici : la
    # puce doit donc rester nue plutôt que d'emprunter le delta d'un autre
    # horizon. C'est le comportement qui empêche « +250 M vs hier » de
    # s'afficher sous l'étiquette « sur 7 j ».
    assert len(res["bullets"]) == 1
    assert "M FCFA" in res["bullets"][0]


@pytest.mark.asyncio
async def test_seuil_regle_change_la_puce():
    """Le seuil n'est plus en dur : le déplacer déplace le texte."""
    strict = await facts.build_dg_facts(
        FauxCRM(), facts.Composition(["concentration"], seuils={"concentration_top5_pct": 10})
    )
    laxiste = await facts.build_dg_facts(
        FauxCRM(), facts.Composition(["concentration"], seuils={"concentration_top5_pct": 99})
    )
    assert "seuil de vigilance 10%" in strict["bullets"][0]
    assert "seuil de vigilance 99%" in laxiste["bullets"][0]
    assert strict["facts"]["concentration_seuil_pct"] == 10


@pytest.mark.asyncio
async def test_seuil_absent_retombe_sur_le_catalogue():
    """Une composition sans seuils reproduit exactement les valeurs d'avant."""
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(["taux_materialisation"]))
    assert res["facts"]["seuil_materialisation_pct"] == 80


def test_taux_de_marge_calcule_sur_les_totaux():
    """Jamais la moyenne des pourcentages.

    `perc_marge_*_moyen` est un AVG() non pondéré de pourcentages par dossier :
    91 dossiers à dénominateur minuscule y tiraient la moyenne provisoire à
    -745 %, et le briefing affichait « marge provisoire moyenne -745,31 % ».
    Le taux se recalcule sur les totaux, qui ne peuvent pas diverger ainsi.
    """
    margins = {
        "ca_provisoire_total": 1_000_000_000, "marge_provisoire_total": 200_000_000,
        "ca_definitif_total": 800_000_000, "marge_definitive_total": 240_000_000,
        "perc_marge_provisoire_moyen": -745.31, "perc_marge_definitive_moyen": -413.6,
    }
    assert facts._taux_marge(margins, "provisoire") == 20.0
    assert facts._taux_marge(margins, "definitif") == 30.0


def test_taux_de_marge_suit_le_nom_reel_des_colonnes():
    """`get_margin_stats` n'accorde pas ses clés symétriquement :
    `ca_definitif_total` mais `marge_definitive_total`. Composer les noms par
    interpolation rendait 0,0 % en silence — sans lever, sans avertir."""
    assert facts._taux_marge(
        {"ca_definitif_total": 100, "marge_definitive_total": 45}, "definitif"
    ) == 45.0


def test_taux_de_marge_sans_ca_ne_rend_pas_zero():
    """Aucun CA constaté n'est pas une marge nulle : la puce doit pouvoir dire
    « non mesurable » plutôt qu'afficher 0 %."""
    assert facts._taux_marge(
        {"ca_definitif_total": 0, "marge_definitive_total": 0}, "definitif"
    ) is None


@pytest.mark.asyncio
async def test_puce_marge_do_nutilise_pas_la_moyenne_de_pourcentages():
    res = await facts.build_dir_operations_facts(FauxCRM(), facts.Composition(["volume_marges"]))
    puce = res["bullets"][0]
    # 2 000 / 10 000 et 3 000 / 9 000 sur les totaux du faux CRM.
    assert "20.0%" in puce and "33.3%" in puce
    assert res["facts"]["marge_provisoire_moyenne_pct"] == 20.0


@pytest.mark.asyncio
async def test_mouvements_sans_rien_le_dit_au_lieu_de_se_taire(monkeypatch):
    """Une puce absente se lit comme une donnée manquante ; une journée calme
    est une information et doit s'écrire."""
    async def _rien(*a, **k):
        return {"depuis": "2026-08-20", "jusqu_a": "2026-08-27", "total_evenements": 0,
                "commandes_entrees": {"nb": 0, "montant_xof": 0, "top": []},
                "factures_emises": {"nb": 0, "montant_xof": 0, "top": []},
                "factures_reglees": {"nb": 0, "montant_xof": 0, "top": []},
                "achats_engages": {"nb": 0, "montant_xof": 0, "top": []},
                "opportunites_retouchees": {"nb": 0, "montant_xof": 0, "top": []},
                "changements_etape": {"mesurable": False, "raison": "pas de snapshot"}}
    monkeypatch.setattr(facts.evenements, "mouvements", _rien)

    res = await facts.build_dir_commercial_facts(
        FauxCRM(), facts.Composition(["mouvements_recents"])
    )
    assert len(res["bullets"]) == 1
    assert "Aucun mouvement" in res["bullets"][0]


@pytest.mark.asyncio
async def test_toute_categorie_comptee_peut_se_dire(monkeypatch):
    """Une catégorie qui entre dans `total_evenements` sans jamais s'afficher
    produit une puce vide (« Depuis le 20/08 : . ») — le défaut exact rencontré
    sur les achats engagés et les retouches d'opportunité."""
    for categorie in ("commandes_entrees", "factures_emises", "factures_reglees",
                      "achats_engages", "opportunites_retouchees"):
        vide = {"nb": 0, "montant_xof": 0, "top": []}
        mvt = {"depuis": "2026-08-20", "jusqu_a": "2026-08-27", "total_evenements": 1,
               "changements_etape": {"mesurable": True, "nb": 0, "top": []},
               **{c: dict(vide) for c in ("commandes_entrees", "factures_emises",
                                          "factures_reglees", "achats_engages",
                                          "opportunites_retouchees")}}
        mvt[categorie] = {"nb": 1, "montant_xof": 5_000_000,
                          "top": [{"ref": "X", "tiers": "CIE", "montant_xof": 5_000_000,
                                   "date": "2026-08-21", "opportunite": "X", "client": "CIE",
                                   "revenu_attendu_xof": 5_000_000, "stade": "1"}]}

        async def _un(*a, _m=mvt, **k):
            return _m
        monkeypatch.setattr(facts.evenements, "mouvements", _un)

        res = await facts.build_dir_commercial_facts(
            FauxCRM(), facts.Composition(["mouvements_recents"])
        )
        puce = res["bullets"][0]
        assert not puce.endswith(" : ."), f"puce vide pour {categorie} : {puce!r}"


@pytest.mark.asyncio
async def test_hygiene_pipe_publie_les_deux_tas():
    """Le nombre « à relancer » et le stock « à assainir » vont ensemble : le
    premier seul laisserait croire que le pipeline publié ailleurs est sincère."""
    res = await facts.build_dir_commercial_facts(
        FauxCRM(), facts.Composition(["hygiene_pipe"])
    )
    puce = res["bullets"][0]
    assert "3 affaire(s)" in puce
    assert "3015" in puce and "échéance déjà dépassée" in puce
    assert res["facts"]["hygiene_a_assainir_nb"] == 3015


def test_doublure_balance_suit_la_vraie_structure(_stub_sources_evolutives):
    """Une doublure qui dérive de la fonction qu'elle remplace ne teste plus
    rien : elle fait passer les tests pendant que la vraie puce lève un
    KeyError en production — le défaut exact rencontré au passage de
    `contentieux` hors des tranches.

    On exécute la VRAIE fonction sur une base vide et on compare les clés :
    comparer le texte de la source ne verrait que la doublure, l'attribut du
    module étant déjà remplacé à ce stade.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from db.database import Base
    from modules.uc_briefing import analyses

    vraie = _stub_sources_evolutives["balance_agee"]

    async def _reelle():
        engine = create_async_engine(
            "sqlite+aiosqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        original = analyses.AsyncSessionLocal
        analyses.AsyncSessionLocal = factory
        try:
            return await vraie()
        finally:
            analyses.AsyncSessionLocal = original
            await engine.dispose()

    reelle = asyncio.run(_reelle())
    assert set(BALANCE_NEUTRE) == set(reelle)
    assert set(BALANCE_NEUTRE["tranches"]) == set(reelle["tranches"])
    assert set(BALANCE_NEUTRE["contentieux"]) == set(reelle["contentieux"])


# ── Ordre de lecture ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("role, builder", list(_FACTS_BUILDERS.items()))
async def test_les_puces_sortent_dans_lordre_du_catalogue(role, builder):
    """Le chiffre, puis l'exception, puis l'action — jamais l'ordre du code.

    Sans ce verrou, la hiérarchie du briefing n'existe nulle part et c'est le
    LLM qui, faute de mieux, choisit les cinq lignes affichées en tête de
    cockpit : un modèle de langage décide alors chaque matin de ce que lit une
    direction. Le test compare l'ordre obtenu à l'ordre du catalogue, bloc par
    bloc.
    """
    tous = [e.id for e in CATALOGUE[role]]
    res = await builder(FauxCRM(), facts.Composition(tous))
    textes = res["bullets"]

    # Reconstruit le rang de chaque puce en la régénérant élément par élément :
    # une puce n'est pas étiquetée dans la sortie, mais chaque élément produit
    # un texte reconnaissable.
    rangs = []
    for element in tous:
        seul = await builder(FauxCRM(), facts.Composition([element]))
        for texte in seul["bullets"]:
            if texte in textes:
                rangs.append((textes.index(texte), preferences.rang(role, element)))

    ordre_obtenu = [rang for _, rang in sorted(rangs)]
    assert ordre_obtenu == sorted(ordre_obtenu), (
        f"les puces de « {role} » ne sortent pas dans l'ordre du catalogue"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role, builder", list(_FACTS_BUILDERS.items()))
async def test_le_bloc_chiffre_ouvre_le_briefing(role, builder):
    """La trame ouvre sur le chiffre et son mouvement, jamais sur une alerte."""
    tous = [e.id for e in CATALOGUE[role]]
    res = await builder(FauxCRM(), facts.Composition(tous))
    premiere = res["bullets"][0]

    chiffres = [e.id for e in CATALOGUE[role] if e.bloc == "chiffre"]
    textes_chiffres = set()
    for element in chiffres:
        seul = await builder(FauxCRM(), facts.Composition([element]))
        textes_chiffres.update(seul["bullets"])
    assert premiere in textes_chiffres


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(CATALOGUE))
async def test_la_couverture_ferme_le_briefing(role):
    """La ligne des questions sans réponse est utile, jamais prioritaire sur un
    fait : elle passe après tout sauf les compléments."""
    builder = _FACTS_BUILDERS[role]
    res = await builder(FauxCRM(), facts.Composition(DEFAUTS[role]))
    assert "restent sans réponse aujourd'hui" in res["bullets"][-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(CATALOGUE))
async def test_chaque_question_de_la_trame_est_servie(role):
    """Toute question déclarée au catalogue produit réellement une puce.

    Une question qui figure dans un libellé sans qu'aucun fait ne la porte est
    exactement le défaut que la refonte corrige — et il est invisible depuis
    l'écran de réglages.
    """
    builder = _FACTS_BUILDERS[role]
    for element in CATALOGUE[role]:
        if not element.question:
            continue
        res = await builder(FauxCRM(), facts.Composition([element.id]))
        assert res["bullets"], (
            f"« {element.question} » ({role}, {element.id}) ne produit aucune puce"
        )
