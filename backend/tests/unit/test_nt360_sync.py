"""Synchro nt360 : correspondance des champs, garde-fous de remplacement,
exclusion intra-groupe et report des objectifs en révisions."""
import pytest
import pytest_asyncio
from datetime import date, datetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from adapters.nt360.nt360_adapter import Nt360AuthError, Nt360Liste
from db.database import Base
from db.models import (
    CommercialObjectiveModel, Nt360BcModel, Nt360CommandeModel, Nt360ConsultationModel,
    Nt360FactureModel, Nt360HistoriqueOppModel, Nt360JalonModel, Nt360OpportuniteModel,
)
from jobs.nt360_sync_job import run_nt360_sync

EXCLU = "NEURONES TECHNOLOGIES BF"   # cf. settings.excluded_partner_names


def _donnees():
    return {
        "commandes": [
            {"fp": "FP/2026/1", "_entite": "CI", "client": "CIE", "cas": 1000, "facture": 400, "raf": 600,
             "yearPo": 2026, "dateCommande": "2026-03-12", "clickupBlocked": False, "nouveauChamp": "x"},
            {"fp": "FP/2026/2", "_entite": "BF", "client": EXCLU.lower(), "cas": 50, "raf": 50},
        ],
        "factures": [
            {"id": "f1", "numero": "FAC/2026/1 ", "fp": "FP/2026/1", "client": "CIE", "date": "2026-09-01",
             "dueDate": "2026-10-01", "amountHt": 400, "paid": True, "regle": 400, "resteAPayer": 0,
             "paymentStatus": "Soldée", "linked": True},
            {"id": "f2", "numero": "FAC/2026/2", "fp": "FP/2026/2", "client": EXCLU, "amountHt": 50},
        ],
        "jalons": [
            {"id": "FP_2026_1", "fp": "FP/2026/1",
             "milestones": [{"date": "2026-11-28", "amount": 200}, {"date": "2026-12-28", "amount": 400}]},
            {"id": "FP_2026_2", "fp": "FP/2026/2", "milestones": [{"date": "2026-11-28", "amount": 50}]},
        ],
        "bc": [
            {"id": "bc1", "fp": "FP/2026/1", "supplier": "WESTCON", "amountXof": 300, "status": "a_emettre"},
            {"id": "bc2", "fp": "FP/2026/2", "supplier": "LGG", "amountXof": 10},
        ],
        "consultations": [
            {"id": "c1", "client": "CIE", "concurrents": ["X", "Y"], "technologies": "Cisco",
             "oppId": "odoo_crm.lead:12900", "cautionMontant": 5000, "dateDepot": "2026-09-01"},
        ],
        "historique-opportunites": [
            {"id": "h1", "oppId": "odoo_crm.lead:12900", "from": 6, "to": 9, "amount": 99,
             "client": "PAYTM", "at": "2026-08-12T14:20:44.723Z"},
            {"id": "h2", "oppId": None, "from": 0, "to": 0, "amount": 0, "at": "2026-08-17T10:12:52.930Z"},
        ],
        # Étape 6 tronquée : la liste rend l'opportunité Odoo, la saisie liée à
        # FP/2026/1 n'est lisible qu'une à une (cf. opportunites_cachees).
        "opportunities": [
            {"id": "odoo_crm.lead:12900", "oppId": "odoo_crm.lead:12900", "client": "CIE", "am": "Koffi",
             "fp": "", "amount": 1000, "stage": 3, "stageLabel": "3-Transmise", "probability": 40,
             "weighted": 400, "closingDate": "2026-12-31", "source": "odoo"},
            {"id": "odoo_crm.lead:12901", "oppId": "odoo_crm.lead:12901", "client": "CIE", "am": "Koffi",
             "fp": "FP/2026/9", "amount": 700, "stage": 6, "stageLabel": "6-Gagné", "probability": 100,
             "source": "odoo"},
            {"id": "x", "client": EXCLU, "stage": 3, "amount": 5},
        ],
        "opportunites_cachees": {
            "saisie_genord_FP_2026_1": {"id": "saisie_genord_FP_2026_1", "client": "CIE", "am": "Koffi",
                                        "fp": "FP/2026/1", "amount": 1000, "stage": 6,
                                        "stageLabel": "6-Gagné", "probability": 100, "source": "saisie"},
        },
        "won_count": 2,
        "objectifs": [
            {"id": "2026_global_all__CI", "fiscalYear": 2026, "scope": "global", "scopeValue": "all",
             "filiale": "CI", "targetCas": 8_800_000_000, "targetInvoiced": 10_000_000_000},
            {"id": "2026_global_all__BF", "fiscalYear": 2026, "scope": "global", "scopeValue": "all",
             "filiale": "BF", "targetCas": 5_000_000_000},
            {"id": "2026_am_x", "fiscalYear": 2026, "scope": "am", "scopeValue": "X", "targetCas": 1},
        ],
    }


class FauxAdapter:
    def __init__(self, donnees, *, incomplet=(), erreurs=None):
        self.donnees = donnees
        self.incomplet = set(incomplet)
        self.erreurs = erreurs or {}
        self.lectures_unitaires: list[str] = []

    async def fetch_all(self, ressource, **filtres):
        if ressource in self.erreurs:
            raise self.erreurs[ressource]
        if "entite" in filtres and (ressource, "entite") in self.erreurs:
            raise self.erreurs[(ressource, "entite")]
        items = list(self.donnees.get(ressource, []))
        if "entite" in filtres:
            items = [o for o in items if o.get("_entite") == filtres["entite"]]
            return Nt360Liste(items=items, pages=1, complete=True)
        if "stage" in filtres:
            items = [o for o in items if o.get("stage") == filtres["stage"]]
            return Nt360Liste(items=items, pages=1,
                              complete=(ressource, filtres["stage"]) not in self.incomplet)
        return Nt360Liste(items=items, pages=1, complete=ressource not in self.incomplet)

    async def get(self, ressource, ident):
        self.lectures_unitaires.append(ident)
        return self.donnees.get("opportunites_cachees", {}).get(ident)

    async def get_synthese(self, nom, entite=None):
        return {"wonCount": self.donnees.get("won_count")}


@pytest_asyncio.fixture
async def sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _sync(sessions, adapter):
    return await run_nt360_sync(adapter, session_factory=sessions, save_status=False,
                                rebaser_indicateurs=False)


async def _all(sessions, model):
    async with sessions() as s:
        return (await s.scalars(select(model))).all()


async def _objectifs(sessions):
    async with sessions() as s:
        return (await s.scalars(select(CommercialObjectiveModel).order_by(
            CommercialObjectiveModel.scope_ref, CommercialObjectiveModel.revision))).all()


# ── Correspondance et exclusion ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synchro_complete_correspondance_des_champs(sessions):
    rapport = await _sync(sessions, FauxAdapter(_donnees()))
    assert rapport["statut"] == "ok"

    [cmd] = await _all(sessions, Nt360CommandeModel)
    assert (cmd.fp, cmd.cas, cmd.raf, cmd.year_po) == ("FP/2026/1", 1000, 600, 2026)
    assert cmd.date_commande == date(2026, 3, 12)
    assert cmd.raw["nouveauChamp"] == "x"           # champ non documenté conservé

    jalons = await _all(sessions, Nt360JalonModel)
    assert [(j.rang, j.date_echeance, j.amount) for j in jalons] == [
        (0, date(2026, 11, 28), 200), (1, date(2026, 12, 28), 400)]

    [c] = await _all(sessions, Nt360ConsultationModel)
    assert c.opp_id == "opp_12900" and c.concurrents == ["X", "Y"]
    assert c.technologies == ["Cisco"] and c.caution_montant == 5000

    [h] = await _all(sessions, Nt360HistoriqueOppModel)   # l'événement vide est écarté
    assert h.opp_id == "opp_12900" and (h.from_stage, h.to_stage) == (6, 9)
    assert h.at == datetime(2026, 8, 12, 14, 20, 44, 723000)


@pytest.mark.asyncio
async def test_partenaire_intra_groupe_exclu_avec_ses_jalons_et_bc(sessions):
    rapport = await _sync(sessions, FauxAdapter(_donnees()))
    assert rapport["fps_exclus"] == 1
    assert {c.fp for c in await _all(sessions, Nt360CommandeModel)} == {"FP/2026/1"}
    assert {j.fp for j in await _all(sessions, Nt360JalonModel)} == {"FP/2026/1"}
    assert {b.id for b in await _all(sessions, Nt360BcModel)} == {"bc1"}
    assert {f.id for f in await _all(sessions, Nt360FactureModel)} == {"f1"}


@pytest.mark.asyncio
async def test_correspondance_des_factures(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    [f] = await _all(sessions, Nt360FactureModel)
    assert (f.numero, f.fp, f.amount_ht, f.paid, f.reste_a_payer) == ("FAC/2026/1", "FP/2026/1", 400, True, 0)
    assert (f.date_facture, f.due_date) == (date(2026, 9, 1), date(2026, 10, 1))


# ── Garde-fous de remplacement ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remplacement_voit_les_suppressions(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    d = _donnees()
    d["bc"] = [{"id": "bc3", "fp": "FP/2026/1", "supplier": "NOUVEAU"}]
    await _sync(sessions, FauxAdapter(d))
    assert {b.id for b in await _all(sessions, Nt360BcModel)} == {"bc3"}


@pytest.mark.asyncio
async def test_liste_incomplete_ne_remplace_rien(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    d = _donnees()
    d["consultations"] = []
    rapport = await _sync(sessions, FauxAdapter(d, incomplet={"consultations"}))
    assert rapport["ressources"]["consultations"]["statut"] == "conservee"
    assert rapport["statut"] == "partiel"
    assert len(await _all(sessions, Nt360ConsultationModel)) == 1


@pytest.mark.asyncio
async def test_reponse_vide_ne_vide_pas_une_table_remplie(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    d = _donnees()
    d["bc"] = []
    rapport = await _sync(sessions, FauxAdapter(d))
    assert rapport["ressources"]["bc"] == {"recus": 0, "lignes": 0, "pages": 1,
                                           "statut": "conservee", "motif": "réponse vide"}
    assert len(await _all(sessions, Nt360BcModel)) == 1


@pytest.mark.asyncio
async def test_commandes_en_echec_gele_jalons_et_bc(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    d = _donnees()
    d["bc"] = [{"id": "bc9", "fp": "FP/2026/2", "supplier": "FUITE"}]   # FP d'un exclu
    rapport = await _sync(sessions, FauxAdapter(d, erreurs={"commandes": RuntimeError("500")}))
    assert rapport["ressources"]["commandes"]["statut"] == "erreur"
    assert rapport["ressources"]["bc"]["motif"] == "commandes indisponibles"
    assert {b.id for b in await _all(sessions, Nt360BcModel)} == {"bc1"}
    assert rapport["ressources"]["consultations"]["statut"] == "ok"   # indépendante


@pytest.mark.asyncio
async def test_cle_refusee_interrompt_tout(sessions):
    rapport = await _sync(sessions, FauxAdapter(_donnees(), erreurs={"commandes": Nt360AuthError("401", 401)}))
    assert rapport["statut"] == "cle_refusee"
    assert rapport["ressources"] == {}                    # arrêt dès la lecture des entités
    assert "objectifs_commerciaux" not in rapport


# ── Objectifs → commercial_objectives ───────────────────────────────────────

@pytest.mark.asyncio
async def test_objectifs_globaux_reportes_par_entite(sessions):
    rapport = await _sync(sessions, FauxAdapter(_donnees()))
    assert rapport["objectifs_commerciaux"] == {
        "crees": 2, "inchanges": 0, "ignores_manuel": 0, "ignores_perimetre": 1}
    objs = await _objectifs(sessions)
    assert [(o.scope, o.scope_ref, o.kind, o.period_type, o.period_year, o.target_amount_xof, o.revision)
            for o in objs] == [
        ("equipe", "BF", "ca", "annee", 2026, 5_000_000_000, 1),
        ("equipe", "CI", "ca", "annee", 2026, 8_800_000_000, 1),
    ]
    assert objs[1].created_by == "nt360" and objs[1].note == "nt360:2026_global_all__CI"


@pytest.mark.asyncio
async def test_objectif_inchange_ne_cree_pas_de_revision(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    rapport = await _sync(sessions, FauxAdapter(_donnees()))
    assert rapport["objectifs_commerciaux"]["crees"] == 0
    assert rapport["objectifs_commerciaux"]["inchanges"] == 2
    assert len(await _objectifs(sessions)) == 2


@pytest.mark.asyncio
async def test_objectif_modifie_cree_une_revision_et_archive_lancienne(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    d = _donnees()
    d["objectifs"][0]["targetCas"] = 9_000_000_000
    await _sync(sessions, FauxAdapter(d))
    ci = [o for o in await _objectifs(sessions) if o.scope_ref == "CI"]
    assert [(o.revision, o.target_amount_xof, o.superseded) for o in ci] == [
        (1, 8_800_000_000, True), (2, 9_000_000_000, False)]


@pytest.mark.asyncio
async def test_objectif_saisi_a_la_main_garde_la_priorite(sessions):
    async with sessions() as s:
        s.add(CommercialObjectiveModel(
            scope="equipe", scope_ref="", kind="ca", period_type="annee", period_year=2026,
            period_index=0, target_amount_xof=12_000_000_000, target_count=0, revision=1,
            superseded=False, note="", created_by="dc@neurones", created_at=datetime(2026, 1, 5),
        ))
        await s.commit()
    rapport = await _sync(sessions, FauxAdapter(_donnees()))
    assert rapport["objectifs_commerciaux"]["ignores_manuel"] == 2
    async with sessions() as s:
        assert await s.scalar(select(func.count()).select_from(CommercialObjectiveModel)) == 1


@pytest.mark.asyncio
async def test_adapter_absent_desactive_la_synchro(sessions):
    assert await _sync(sessions, None) == {"statut": "desactivee"}


# ── Opportunités : liste tronquée + récupération unitaire ───────────────────

TRONQUEE = {("opportunities", 6)}


@pytest.mark.asyncio
async def test_opportunites_gagnees_tronquees_relues_une_a_une(sessions):
    adapter = FauxAdapter(_donnees(), incomplet=TRONQUEE)
    rapport = await _sync(sessions, adapter)
    etat = rapport["ressources"]["opportunities"]
    assert etat["statut"] == "ok" and etat["etapes_tronquees"] == [6]
    assert etat["gagnees_lues"] == 2 and etat["gagnees_nt360"] == 2 and etat["complet"] is True
    # FP/2026/2 appartient au partenaire exclu : jamais relu
    assert adapter.lectures_unitaires == ["saisie_genord_FP_2026_1"]
    rows = {o.id: o for o in await _all(sessions, Nt360OpportuniteModel)}
    assert set(rows) == {"odoo_crm.lead:12900", "odoo_crm.lead:12901", "saisie_genord_FP_2026_1"}
    assert rows["odoo_crm.lead:12900"].opp_id == "opp_12900"
    assert rows["saisie_genord_FP_2026_1"].lecture == "unitaire" and rows["saisie_genord_FP_2026_1"].opp_id is None


@pytest.mark.asyncio
async def test_sans_troncature_aucune_relecture(sessions):
    adapter = FauxAdapter(_donnees())
    rapport = await _sync(sessions, adapter)
    assert adapter.lectures_unitaires == []
    assert rapport["ressources"]["opportunities"]["complet"] is False     # 1 gagnée lue pour 2 annoncées


@pytest.mark.asyncio
async def test_relecture_au_plus_une_fois_par_fenetre_et_gagnees_conservees(sessions):
    await _sync(sessions, FauxAdapter(_donnees(), incomplet=TRONQUEE))
    second = FauxAdapter(_donnees(), incomplet=TRONQUEE)
    await _sync(sessions, second)
    assert second.lectures_unitaires == []                                 # < RECUPERATION_HEURES
    ids = {o.id for o in await _all(sessions, Nt360OpportuniteModel)}
    assert "saisie_genord_FP_2026_1" in ids                                # relue la veille, gardée


@pytest.mark.asyncio
async def test_relecture_forcee(sessions):
    await _sync(sessions, FauxAdapter(_donnees(), incomplet=TRONQUEE))
    second = FauxAdapter(_donnees(), incomplet=TRONQUEE)
    await run_nt360_sync(second, session_factory=sessions, save_status=False,
                         rebaser_indicateurs=False, forcer_recuperation=True)
    assert second.lectures_unitaires == ["saisie_genord_FP_2026_1"]


@pytest.mark.asyncio
async def test_lecture_unitaire_en_echec_garde_la_gagnee_connue(sessions):
    from adapters.nt360.nt360_adapter import Nt360Error
    await _sync(sessions, FauxAdapter(_donnees(), incomplet=TRONQUEE))

    class EnEchec(FauxAdapter):
        async def get(self, ressource, ident):
            raise Nt360Error("429 persistant", 429)

    rapport = await run_nt360_sync(EnEchec(_donnees(), incomplet=TRONQUEE), session_factory=sessions,
                                   save_status=False, rebaser_indicateurs=False, forcer_recuperation=True)
    assert rapport["ressources"]["opportunities"]["recuperation"]["erreurs"] == 1
    rows = {o.id: o for o in await _all(sessions, Nt360OpportuniteModel)}
    assert rows["saisie_genord_FP_2026_1"].lecture == "unitaire"


@pytest.mark.asyncio
async def test_fp_deja_porte_par_la_liste_nest_pas_relu(sessions):
    """FP/2026/9 est porté par odoo_crm.lead:12901 (liste) : sa saisie générée
    ne doit pas être relue, sinon la même affaire gagnée compte deux fois."""
    d = _donnees()
    d["commandes"].append({"fp": "FP/2026/9", "client": "CIE", "cas": 700})
    d["opportunites_cachees"]["saisie_genord_FP_2026_9"] = {"id": "saisie_genord_FP_2026_9", "fp": "FP/2026/9",
                                                            "stage": 6, "client": "CIE", "amount": 700}
    adapter = FauxAdapter(d, incomplet=TRONQUEE)
    await _sync(sessions, adapter)
    assert "saisie_genord_FP_2026_9" not in adapter.lectures_unitaires


# ── Ressources en attente de droits ─────────────────────────────────────────

FACULTATIVES = ["alertes", "accounts", "reglements", "demandes-facturation", "fiches", "plafonds-fournisseurs"]


def _droits_ouverts():
    d = _donnees()
    d.update({
        "alertes": [{"type": "raf_sans_date", "severity": "warning", "count": 2, "message": "2 FP sans date",
                     "refs": ["FP/2026/1", "FP/2026/2"]}],
        "accounts": [{"id": "a1", "name": "CIE", "sector": "Énergie", "country": "CI", "parentId": None,
                      "tags": ["grand compte"]},
                     {"id": "a2", "name": EXCLU}],
        "reglements": [{"id": "r1", "factureId": "f1", "numero": "FAC/2026/1", "client": "CIE",
                        "date": "2026-10-02", "montant": 400, "mode": "virement", "reference": "VIR-1"}],
        "demandes-facturation": [{"id": "d1", "fp": "FP/2026/1", "client": "CIE", "montant": 200,
                                  "dateSouhaitee": "2026-11-15", "statut": "en_attente",
                                  "creeeLe": "2026-10-10T08:00:00.000Z"},
                                 {"id": "d2", "fp": "FP/2026/2", "client": "X", "montant": 5}],
        "fiches": [{"id": "fi1", "numero_fp": "FP/2026/1", "numero_dc": "DC/2026/1", "client": "CIE",
                    "prix_vente_ht_xof": 1000, "date_fiche": "2026-03-01", "terminee": True},
                   {"id": "fi2", "numero_fp": "FP/2026/2", "client": "X"}],
        "plafonds-fournisseurs": [{"name": "WESTCON", "authorized": 5e8, "openingBalance": 1e8,
                                   "openingDate": "2026-01-01"}],
    })
    return d


@pytest.mark.asyncio
async def test_ressources_vides_ne_rendent_pas_la_synchro_partielle(sessions):
    rapport = await _sync(sessions, FauxAdapter(_donnees(), incomplet={("opportunities", 6)}))
    for nom in FACULTATIVES:
        assert rapport["ressources"][nom]["statut"] == "ok", nom
    assert rapport["ressources"]["reglements"].get("vide") is True
    assert rapport["statut"] == "ok"


@pytest.mark.asyncio
async def test_403_sur_ressource_facultative_ne_bloque_rien(sessions):
    adapter = FauxAdapter(_donnees(), incomplet={("opportunities", 6)},
                          erreurs={"reglements": Nt360AuthError("clé sans le droit requis", 403)})
    rapport = await _sync(sessions, adapter)
    assert rapport["ressources"]["reglements"]["statut"] == "non_autorisee"
    assert rapport["ressources"]["fiches"]["statut"] == "ok"            # la suite continue
    assert rapport["statut"] == "ok"


@pytest.mark.asyncio
async def test_401_interrompt_meme_sur_ressource_facultative(sessions):
    adapter = FauxAdapter(_donnees(), erreurs={"reglements": Nt360AuthError("clé révoquée", 401)})
    rapport = await _sync(sessions, adapter)
    assert rapport["statut"] == "cle_refusee"


@pytest.mark.asyncio
async def test_droits_ouverts_remplissent_les_tables_sans_intervention(sessions):
    from db.models import (
        Nt360AlerteModel, Nt360CompteModel, Nt360DemandeFacturationModel, Nt360FicheModel,
        Nt360PlafondFournisseurModel, Nt360ReglementModel,
    )
    await _sync(sessions, FauxAdapter(_donnees()))                      # aujourd'hui : vides
    rapport = await _sync(sessions, FauxAdapter(_droits_ouverts()))     # le jour où les droits arrivent
    for nom in FACULTATIVES:
        assert rapport["ressources"][nom].get("premiere_alimentation") is True, nom

    [alerte] = await _all(sessions, Nt360AlerteModel)
    assert alerte.refs == ["FP/2026/1"]                                 # FP du partenaire exclu retiré
    assert {c.id for c in await _all(sessions, Nt360CompteModel)} == {"a1"}
    [r] = await _all(sessions, Nt360ReglementModel)
    assert (r.numero, r.date_reglement, r.montant) == ("FAC/2026/1", date(2026, 10, 2), 400)
    [dm] = await _all(sessions, Nt360DemandeFacturationModel)
    assert dm.id == "d1" and dm.creee_le == datetime(2026, 10, 10, 8, 0)
    [fi] = await _all(sessions, Nt360FicheModel)
    assert fi.id == "fi1" and fi.terminee is True
    [p] = await _all(sessions, Nt360PlafondFournisseurModel)
    assert (p.name, p.authorized, p.opening_date) == ("WESTCON", 5e8, date(2026, 1, 1))


@pytest.mark.asyncio
async def test_alertes_resolues_disparaissent_mais_pas_les_comptes(sessions):
    from db.models import Nt360AlerteModel, Nt360CompteModel
    await _sync(sessions, FauxAdapter(_droits_ouverts()))
    rapport = await _sync(sessions, FauxAdapter(_donnees()))            # réponses vides
    assert await _all(sessions, Nt360AlerteModel) == []                 # plus d'alerte : table vidée
    assert len(await _all(sessions, Nt360CompteModel)) == 1             # incident API : comptes gardés
    assert rapport["ressources"]["accounts"]["statut"] == "conservee"


# ── Entités (filtre ?entite=) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_entite_posee_sur_chaque_commande(sessions):
    rapport = await _sync(sessions, FauxAdapter(_donnees()))
    assert rapport["entites"] == {"statut": "ok", "CI": 1, "BF": 1, "GN": 0}
    [cmd] = await _all(sessions, Nt360CommandeModel)                     # FP/2026/2 exclu
    assert (cmd.fp, cmd.entite) == ("FP/2026/1", "CI")


@pytest.mark.asyncio
async def test_entite_conservee_si_la_lecture_filtree_echoue(sessions):
    await _sync(sessions, FauxAdapter(_donnees()))
    rapport = await _sync(sessions, FauxAdapter(_donnees(), erreurs={("commandes", "entite"): RuntimeError("500")}))
    assert rapport["entites"]["statut"] == "conservee"
    [cmd] = await _all(sessions, Nt360CommandeModel)
    assert cmd.entite == "CI"


@pytest.mark.asyncio
async def test_alertes_lues_pour_le_groupe_et_par_entite(sessions):
    from db.models import Nt360AlerteModel
    d = _droits_ouverts()
    d["alertes"].append({"_entite": "BF", "type": "raf_bf", "severity": "low", "count": 1, "message": "BF"})
    await _sync(sessions, FauxAdapter(d))
    par = sorted((a.entite, a.type) for a in await _all(sessions, Nt360AlerteModel))
    # la lecture globale rend aussi l'alerte BF ; la lecture filtrée la rattache à BF
    assert ("BF", "raf_bf") in par and ("", "raf_sans_date") in par
