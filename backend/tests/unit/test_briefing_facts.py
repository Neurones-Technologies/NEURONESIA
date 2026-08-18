"""Composition du débrief : gating des faits par élément coché.

Le test central est `test_sans_composition_produit_le_briefing_historique` — il
verrouille le fait que le refactor de gating n'a rien changé pour les
installations sans préférence enregistrée. Les autres portent sur ce qui casse
en silence : une source interrogée pour rien, une source partagée oubliée, une
action du jour citant un dossier dont plus aucune puce ne parle.
"""
import pytest

from modules.uc_briefing import facts
from modules.uc_briefing.preferences import CATALOGUE, DEFAUTS


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


# ── Non-régression ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sans_composition_produit_le_briefing_historique():
    """Aucune préférence enregistrée = tout est actif, comme avant le gating."""
    res = await facts.build_dg_facts(FauxCRM())
    assert len(res["bullets"]) == len(CATALOGUE["dg"])
    assert res["action"]
    assert res["facts"]["date_arret"]


@pytest.mark.asyncio
async def test_defauts_reproduisent_les_sept_blocs_dorigine():
    res = await facts.build_dg_facts(FauxCRM(), facts.Composition(DEFAUTS["dg"]))
    assert len(res["bullets"]) == 7
    # Les deux éléments ajoutés après coup restent hors du briefing par défaut.
    assert "retention_taux_pct" not in res["facts"]
    assert "fournisseurs_top_nom" not in res["facts"]


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

    async def _panne():
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
