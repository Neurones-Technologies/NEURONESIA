"""Synchro nt360 → tables `nt360_*` (+ objectifs → `commercial_objectives`).

Remplacement COMPLET de chaque table à chaque passage : l'API n'offre aucun
filtre « modifié depuis », et seul un remplacement voit les suppressions. Deux
garde-fous empêchent qu'un incident côté nt360 vide une table :

- une liste marquée incomplète (troncature, garde-fou de pages) ne remplace rien ;
- une réponse vide ne remplace pas une table qui contient des lignes.

Dans les deux cas la table garde son dernier état connu, et le rapport le dit.

Exclusion intra-groupe : même règle que la synchro Odoo (nom EXACT, casse
ignorée, cf. settings.excluded_partner_names). Jalons et BC ne portent pas le
nom du client : ils sont écartés par le N° FP des commandes exclues, d'où
l'ordre de traitement (commandes d'abord) et leur dépendance à celle-ci.
"""
import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import delete, func, select

from adapters.nt360.nt360_adapter import Nt360Adapter, Nt360AuthError, Nt360Liste
from config.settings import settings
from db.database import AsyncSessionLocal
from db.models import (
    CommercialObjectiveModel, Nt360BcModel, Nt360CommandeModel, Nt360ConsultationModel,
    Nt360FactureModel, Nt360HistoriqueOppModel, Nt360JalonModel, Nt360ObjectifModel,
    Nt360AlerteModel, Nt360CompteModel, Nt360DemandeFacturationModel, Nt360FicheModel,
    Nt360OpportuniteModel, Nt360PlafondFournisseurModel, Nt360ReglementModel,
)

logger = logging.getLogger(__name__)

_STATUS_FILE = settings.local_db_path.parent / "last_sync_nt360.json"

# Auteur des révisions d'objectifs écrites par la synchro : c'est ce qui les
# distingue d'un objectif saisi à la main, qui garde toujours la priorité.
AUTEUR_OBJECTIFS = "nt360"


# ── Conversions ─────────────────────────────────────────────────────────────

def _s(v) -> str:
    return "" if v is None else str(v)


def _f(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _d(v) -> date | None:
    """Date métier nt360 (AAAA-MM-JJ). None si absente ou illisible."""
    if not v or not isinstance(v, str) or len(v) < 10:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        logger.warning("nt360 : date invalide ignorée : %r", v)
        return None


def _ts(v) -> datetime | None:
    """Horodatage ISO 8601 UTC (2026-10-19T08:00:00.000Z) → datetime naïf UTC,
    comme le reste de la base (datetime.utcnow)."""
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        logger.warning("nt360 : horodatage invalide ignoré : %r", v)
        return None


def _opp_local(opp_id) -> str | None:
    """`odoo_crm.lead:12900` → `opp_12900`, la clé du miroir `opportunities`."""
    if not isinstance(opp_id, str) or not opp_id.startswith("odoo_crm.lead:"):
        return None
    suffixe = opp_id.split(":", 1)[1]
    return f"opp_{suffixe}" if suffixe.isdigit() else None


def _exclu(nom) -> bool:
    if not nom:
        return False
    return str(nom).strip().upper() in {n.strip().upper() for n in settings.excluded_partner_names}


# ── Correspondance ressource → lignes ───────────────────────────────────────
# Chaque fonction reçoit un élément nt360 et le contexte de la synchro, et rend
# 0..n lignes (les jalons d'un FP sont dépliés, un élément exclu n'en rend aucune).

def _commande(d: dict, ctx: dict) -> list[dict]:
    if not d.get("fp"):
        return []
    if _exclu(d.get("client")):
        ctx["fps_exclus"].add(d["fp"])
        return []
    return [{
        "fp": d["fp"], "entite": ctx.get("entite_par_fp", {}).get(d["fp"], ""),
        "client": _s(d.get("client")), "affaire": _s(d.get("affaire")),
        "bu": _s(d.get("bu")), "am": _s(d.get("am")), "pm": _s(d.get("pm")),
        "sales_team": _s(d.get("salesTeam")),
        "cas": _f(d.get("cas")) or 0.0, "facture": _f(d.get("facture")) or 0.0, "raf": _f(d.get("raf")) or 0.0,
        "year_po": d.get("yearPo") if isinstance(d.get("yearPo"), int) else None,
        "date_commande": _d(d.get("dateCommande")), "date_demarrage": _d(d.get("dateDemarrage")),
        "date_contractuelle": _d(d.get("dateContractuelle")), "date_fin_prev": _d(d.get("dateFinPrev")),
        "couverture": _s(d.get("couverture")), "pf_niveau": _s(d.get("pfNiveau")),
        "clickup_status": _s(d.get("clickupStatus")), "clickup_progress": _f(d.get("clickupProgress")),
        "clickup_blocked": bool(d.get("clickupBlocked")), "raw": d,
    }]


def _facture(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or d.get("fp") in ctx["fps_exclus"] or _exclu(d.get("client")):
        return []
    return [{
        "id": d["id"], "numero": _s(d.get("numero")).strip(), "fp": _s(d.get("fp")), "dc": _s(d.get("dc")),
        "client": _s(d.get("client")), "bu": _s(d.get("bu")), "filiale": _s(d.get("filiale")),
        "date_facture": _d(d.get("date")), "due_date": _d(d.get("dueDate")),
        "amount_ht": _f(d.get("amountHt")) or 0.0, "currency": _s(d.get("currency")) or "XOF",
        "amount_currency": _f(d.get("amountCurrency")), "fx_rate": _f(d.get("fxRate")),
        "payment_status": _s(d.get("paymentStatus")), "paid": bool(d.get("paid")),
        "regle": _f(d.get("regle")) or 0.0, "reste_a_payer": _f(d.get("resteAPayer")) or 0.0,
        "linked": bool(d.get("linked")), "raw": d,
    }]


def _jalons(d: dict, ctx: dict) -> list[dict]:
    fp = d.get("fp")
    if not fp or fp in ctx["fps_exclus"]:
        return []
    return [
        {"fp": fp, "rang": i, "date_echeance": _d(m.get("date")), "amount": _f(m.get("amount")) or 0.0}
        for i, m in enumerate(d.get("milestones") or [])
        if isinstance(m, dict)
    ]


def _bc(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or d.get("fp") in ctx["fps_exclus"] or _exclu(d.get("customer")):
        return []
    return [{
        "id": d["id"], "bc_number": _s(d.get("bcNumber")), "fp": _s(d.get("fp")), "dc": _s(d.get("dc")),
        "supplier": _s(d.get("supplier")), "customer": _s(d.get("customer")), "filiale": _s(d.get("filiale")),
        "description": _s(d.get("description")), "expense_type": _s(d.get("expenseType")),
        "amount_xof": _f(d.get("amountXof")) or 0.0, "currency": _s(d.get("currency")) or "XOF",
        "status": _s(d.get("status")), "date_in": _d(d.get("dateIn")),
        "eta_contrat": _d(d.get("etaContrat")), "eta_reel": _d(d.get("etaReel")),
        "source": _s(d.get("source")), "raw": d,
    }]


def _consultation(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or _exclu(d.get("client")):
        return []
    techno = d.get("technologies")
    concurrents = d.get("concurrents")
    return [{
        "id": d["id"], "filiale": _s(d.get("filiale")), "type": _s(d.get("type")),
        "client": _s(d.get("client")), "intitule": _s(d.get("intitule")), "secteur": _s(d.get("secteur")),
        "technologies": techno if isinstance(techno, list) else ([techno] if techno else []),
        "date_entree": _d(d.get("dateEntree")), "date_soumission": _d(d.get("dateSoumission")),
        "date_depot": _d(d.get("dateDepot")),
        "decision": _s(d.get("decision")), "statut": _s(d.get("statut")), "issue": _s(d.get("issue")),
        "motif_no_go": _s(d.get("motifNoGo")), "motif_perte": _s(d.get("motifPerte")),
        "am": _s(d.get("am")), "avant_vente": _s(d.get("avantVente")),
        "montant": _f(d.get("montant")),
        "concurrents": concurrents if isinstance(concurrents, list) else ([concurrents] if concurrents else []),
        "attributaire": _s(d.get("attributaire")), "prix_attribue": _f(d.get("prixAttribue")),
        "caution_montant": _f(d.get("cautionMontant")),
        "opp_id": _opp_local(d.get("oppId")), "raw": d,
    }]


def _historique(d: dict, ctx: dict) -> list[dict]:
    # Le sondage a trouvé des événements vides (oppId null, 0 → 0) : sans
    # opportunité ils ne disent rien et sont écartés.
    if not d.get("id") or not d.get("oppId") or _exclu(d.get("client")):
        return []
    return [{
        "id": d["id"], "opp_id": _opp_local(d.get("oppId")),
        "from_stage": d.get("from") if isinstance(d.get("from"), int) else None,
        "to_stage": d.get("to") if isinstance(d.get("to"), int) else None,
        "amount": _f(d.get("amount")) or 0.0, "client": _s(d.get("client")),
        "am": _s(d.get("am")), "bu": _s(d.get("bu")), "at": _ts(d.get("at")),
    }]


def _objectif(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or not isinstance(d.get("fiscalYear"), int):
        return []
    return [{
        "id": d["id"], "label": _s(d.get("label")), "fiscal_year": d["fiscalYear"],
        "scope": _s(d.get("scope")), "scope_value": _s(d.get("scopeValue")), "filiale": _s(d.get("filiale")),
        "target_cas": _f(d.get("targetCas")) or 0.0, "target_invoiced": _f(d.get("targetInvoiced")) or 0.0,
        "target_margin": _f(d.get("targetMargin")) or 0.0,
        "target_margin_pct": _f(d.get("targetMarginPct")) or 0.0,
    }]


# Ordre significatif : `commandes` remplit ctx["fps_exclus"] dont dépendent jalons et BC.
# ── Ressources en attente de droits (vides pour notre clé au 2026-10-19) ─────

def _alerte(d: dict, ctx: dict) -> list[dict]:
    refs = d.get("refs")
    refs = refs if isinstance(refs, list) else ([refs] if refs else [])
    # Les N° FP d'un partenaire exclu ne doivent apparaître nulle part.
    refs = [r for r in refs if r not in ctx["fps_exclus"]]
    return [{
        "type": _s(d.get("type")), "severity": _s(d.get("severity")),
        "count": d.get("count") if isinstance(d.get("count"), int) else 0,
        "message": _s(d.get("message")), "refs": refs, "raw": d,
    }]


def _compte(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or _exclu(d.get("name")):
        return []
    tags = d.get("tags")
    return [{
        "id": _s(d["id"]), "name": _s(d.get("name")), "sector": _s(d.get("sector")),
        "country": _s(d.get("country")), "parent_id": _s(d.get("parentId")),
        "tags": tags if isinstance(tags, list) else ([tags] if tags else []), "raw": d,
    }]


def _reglement(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or _exclu(d.get("client")):
        return []
    return [{
        "id": _s(d["id"]), "facture_id": _s(d.get("factureId")), "numero": _s(d.get("numero")).strip(),
        "client": _s(d.get("client")), "date_reglement": _d(d.get("date")),
        "montant": _f(d.get("montant")) or 0.0, "mode": _s(d.get("mode")),
        "reference": _s(d.get("reference")), "raw": d,
    }]


def _demande_facturation(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or d.get("fp") in ctx["fps_exclus"] or _exclu(d.get("client")):
        return []
    return [{
        "id": _s(d["id"]), "fp": _s(d.get("fp")), "client": _s(d.get("client")), "affaire": _s(d.get("affaire")),
        "montant": _f(d.get("montant")) or 0.0, "libelle": _s(d.get("libelle")),
        "date_souhaitee": _d(d.get("dateSouhaitee")), "jalon": _s(d.get("jalon")),
        "statut": _s(d.get("statut")), "numero": _s(d.get("numero")), "motif": _s(d.get("motif")),
        "creee_le": _ts(d.get("creeeLe")) or (datetime.combine(_d(d.get("creeeLe")), datetime.min.time())
                                             if _d(d.get("creeeLe")) else None),
        "reste_au_depot": _f(d.get("resteAuDepot")), "demandeur_nom": _s(d.get("demandeurNom")), "raw": d,
    }]


def _fiche(d: dict, ctx: dict) -> list[dict]:
    if not d.get("id") or d.get("numero_fp") in ctx["fps_exclus"] or _exclu(d.get("client")):
        return []
    return [{
        "id": _s(d["id"]), "numero_fp": _s(d.get("numero_fp")), "numero_dc": _s(d.get("numero_dc")),
        "client": _s(d.get("client")), "affaire": _s(d.get("affaire")), "commercial": _s(d.get("commercial")),
        "po_client_ref": _s(d.get("po_client_ref")), "po_client_date": _d(d.get("po_client_date")),
        "date_fiche": _d(d.get("date_fiche")), "prix_vente_ht_xof": _f(d.get("prix_vente_ht_xof")) or 0.0,
        "statut": _s(d.get("statut")), "etape_courante": _s(d.get("etape_courante")),
        "terminee": bool(d.get("terminee")), "raw": d,
    }]


def _plafond(d: dict, ctx: dict) -> list[dict]:
    nom = _s(d.get("name") or d.get("id")).strip()
    if not nom:
        return []
    return [{
        "name": nom, "authorized": _f(d.get("authorized")), "opening_balance": _f(d.get("openingBalance")),
        "opening_date": _d(d.get("openingDate")), "raw": d,
    }]


@dataclass(frozen=True)
class Ressource:
    nom: str                          # chemin de l'API
    table: type
    correspondance: Callable[[dict, dict], list[dict]]
    depend_commandes: bool = False    # a besoin des FP exclus (lus avec les commandes)
    # Ressource facultative : un 403 (« clé sans le droit requis ») la marque
    # « non_autorisee » sans interrompre la synchro. Un 401 (clé révoquée)
    # interrompt toujours tout.
    facultative: bool = False
    # Une réponse vide remplace la table (alertes : une alerte résolue disparaît).
    # Sinon, une réponse vide ne vide jamais une table remplie.
    vide_autorise: bool = False
    # Lue pour le groupe puis pour chaque entité (`?entite=`), chaque ligne
    # portant sa colonne `entite` ("" = groupe).
    par_entite: bool = False


# Entités du groupe, au sens du filtre `?entite=` de l'API.
ENTITES = ("CI", "BF", "GN")


async def _entites_commandes(adapter: Nt360Adapter, session_factory) -> tuple[dict[str, str], str]:
    """N° FP → entité, depuis `commandes?entite=…` (le champ `filiale` documenté
    n'est pas renvoyé). Trois lectures complètes ou rien : une lecture partielle
    laisserait des commandes sans entité. En cas d'échec, on garde la
    correspondance de la synchro précédente. Rend (correspondance, état)."""
    async with session_factory() as session:
        precedente = {fp: e for fp, e in (await session.execute(
            select(Nt360CommandeModel.fp, Nt360CommandeModel.entite).where(Nt360CommandeModel.entite != "")
        )).all()}
    fraiche: dict[str, str] = {}
    try:
        for entite in ENTITES:
            res = await adapter.fetch_all("commandes", entite=entite)
            if not res.complete:
                raise ValueError(f"liste incomplète pour l'entité {entite}")
            for d in res.items:
                if d.get("fp"):
                    fraiche[d["fp"]] = entite
    except Nt360AuthError:
        raise
    except Exception as e:
        logger.warning("nt360 : entités des commandes non relues (%s), correspondance précédente conservée", e)
        return precedente, "conservee"
    return fraiche, "ok"


# Ordre significatif : `commandes` remplit ctx["fps_exclus"] dont dépendent les suivantes.
RESSOURCES: list[Ressource] = [
    Ressource("commandes", Nt360CommandeModel, _commande),
    Ressource("factures", Nt360FactureModel, _facture, depend_commandes=True),
    Ressource("jalons", Nt360JalonModel, _jalons, depend_commandes=True),
    Ressource("bc", Nt360BcModel, _bc, depend_commandes=True),
    Ressource("consultations", Nt360ConsultationModel, _consultation),
    Ressource("historique-opportunites", Nt360HistoriqueOppModel, _historique),
    Ressource("objectifs", Nt360ObjectifModel, _objectif),
    # En attente de droits : se remplissent seules le jour où nt360 les ouvre.
    Ressource("alertes", Nt360AlerteModel, _alerte, depend_commandes=True, facultative=True,
              vide_autorise=True, par_entite=True),
    Ressource("accounts", Nt360CompteModel, _compte, facultative=True),
    Ressource("reglements", Nt360ReglementModel, _reglement, facultative=True),
    Ressource("demandes-facturation", Nt360DemandeFacturationModel, _demande_facturation,
              depend_commandes=True, facultative=True),
    Ressource("fiches", Nt360FicheModel, _fiche, depend_commandes=True, facultative=True),
    Ressource("plafonds-fournisseurs", Nt360PlafondFournisseurModel, _plafond, facultative=True),
]


# ── Opportunités : liste tronquée + récupération unitaire ───────────────────
# `opportunities` n'a ni pagination ni curseur (sondé : apres/offset/page/after
# ignorés) et plafonne à 500 par étape. Seule l'étape 6 (Gagné, 1 864 affaires)
# déborde. Triée par identifiant, elle rend toutes les `odoo_crm.lead:*` puis
# coupe dans les `saisie_genord_<FP>` — dont l'identifiant se reconstruit depuis
# les N° FP de nt360_commandes. Une relecture unitaire de ~3 000 FP prend 5 à
# 6 minutes sous le quota (600 req/min) : elle ne tourne qu'une fois par
# fenêtre de RECUPERATION_HEURES, la liste (10 appels) à chaque passage.
ETAPES_OPPORTUNITE = range(10)
RECUPERATION_HEURES = 20
_RECUPERATION_PARALLELE = 5     # le débit est borné par le limiteur de l'adapter (9 req/s)


def _opportunite(d: dict, ctx: dict, lecture: str) -> dict | None:
    if not d.get("id") or _exclu(d.get("client")) or (d.get("fp") and d["fp"] in ctx["fps_exclus"]):
        return None
    etape = d.get("stage")
    return {
        "id": d["id"], "opp_id": _opp_local(d.get("oppId") or d["id"]), "source": _s(d.get("source")),
        "client": _s(d.get("client")), "am": _s(d.get("am")), "bu": _s(d.get("bu")), "fp": _s(d.get("fp")),
        "amount": _f(d.get("amount")) or 0.0, "stage": etape if isinstance(etape, int) else None,
        "stage_label": _s(d.get("stageLabel")), "probability": _f(d.get("probability")) or 0.0,
        "weighted": _f(d.get("weighted")) or 0.0, "closing_date": _d(d.get("closingDate")),
        "forecast_category": _s(d.get("forecastCategory")), "lecture": lecture, "raw": d,
    }


async def _sync_opportunites(adapter: Nt360Adapter, session_factory, ctx: dict,
                             forcer_recuperation: bool = False) -> dict:
    liste: dict[str, dict] = {}
    incompletes: set[int] = set()
    pages = 0
    for etape in ETAPES_OPPORTUNITE:
        res = await adapter.fetch_all("opportunities", stage=etape)
        pages += res.pages
        if not res.complete:
            incompletes.add(etape)
        for d in res.items:
            if d.get("id"):
                liste[d["id"]] = d
    if not liste:
        return {"recus": 0, "lignes": 0, "pages": pages, "statut": "conservee", "motif": "réponse vide"}

    async with session_factory() as session:
        derniere = await session.scalar(
            select(func.max(Nt360OpportuniteModel.synced_at)).where(Nt360OpportuniteModel.lecture == "unitaire"))
        fps = (await session.scalars(select(Nt360CommandeModel.fp))).all()

    a_recuperer = bool(incompletes) and (
        forcer_recuperation or derniere is None
        or datetime.utcnow() - derniere > timedelta(hours=RECUPERATION_HEURES)
    )
    unitaires: list[dict] = []
    recuperation = None
    if a_recuperer:
        # Un FP déjà porté par une opportunité de la liste n'est pas relu : nt360
        # peut garder à la fois l'opportunité Odoo et la saisie générée depuis la
        # commande (FP/2026/12759), mais ne la compte qu'une fois dans wonCount.
        fps_portes = {d.get("fp") for d in liste.values() if d.get("fp")}
        candidats = [
            i for i in (f"saisie_genord_{fp.replace('/', '_')}" for fp in fps
                        if fp not in ctx["fps_exclus"] and fp not in fps_portes)
            if i not in liste
        ]
        sem = asyncio.Semaphore(_RECUPERATION_PARALLELE)

        async def lire(ident: str):
            async with sem:
                return await adapter.get("opportunities", ident)

        resultats = await asyncio.gather(*(lire(i) for i in candidats), return_exceptions=True)
        echecs = {i for i, r in zip(candidats, resultats) if isinstance(r, Exception)}
        auth = [r for r in resultats if isinstance(r, Nt360AuthError)]
        if auth:
            raise auth[0]
        trouvees = [r for r in resultats if isinstance(r, dict)]
        recuperation = {"candidats": len(candidats), "trouvees": len(trouvees), "erreurs": len(echecs)}
        unitaires = [r for d in trouvees if (r := _opportunite(d, ctx, "unitaire"))]
        if echecs:
            # Une lecture en échec ne doit pas faire disparaître une gagnée déjà
            # connue : pour ces seuls identifiants, on garde la relecture précédente.
            logger.warning("nt360 opportunités : %d lecture(s) unitaire(s) en échec, état précédent conservé",
                           len(echecs))
            async with session_factory() as session:
                anciennes = (await session.scalars(select(Nt360OpportuniteModel).where(
                    Nt360OpportuniteModel.lecture == "unitaire", Nt360OpportuniteModel.id.in_(list(echecs))
                ))).all()
            unitaires += [
                {c.name: getattr(o, c.name) for c in Nt360OpportuniteModel.__table__.columns if c.name != "synced_at"}
                for o in anciennes
            ]

    rows = [r for d in liste.values() if (r := _opportunite(d, ctx, "liste"))]
    maintenant = datetime.utcnow()
    async with session_factory() as session:
        if a_recuperer:
            await session.execute(delete(Nt360OpportuniteModel))
            rows += [u for u in unitaires if u["id"] not in liste]
        else:
            # Sans relecture : on remplace ce que la liste a rendu, et on garde
            # les gagnées relues lors de la dernière récupération.
            await session.execute(delete(Nt360OpportuniteModel).where(
                (Nt360OpportuniteModel.lecture == "liste") | (Nt360OpportuniteModel.id.in_(list(liste)))))
        session.add_all(Nt360OpportuniteModel(**r, synced_at=maintenant) for r in rows)
        await session.commit()
        gagnees = await session.scalar(
            select(func.count()).select_from(Nt360OpportuniteModel).where(Nt360OpportuniteModel.stage == 6))

    etat: dict = {"recus": len(liste), "lignes": len(rows), "pages": pages, "statut": "ok",
                  "etapes_tronquees": sorted(incompletes), "gagnees_lues": gagnees}
    if recuperation:
        etat["recuperation"] = recuperation
    # Exhaustivité : nt360 publie son propre décompte des gagnées.
    try:
        won = (await adapter.get_synthese("pipeline") or {}).get("wonCount")
    except Exception as e:   # contrôle seulement : jamais bloquant
        logger.warning("nt360 opportunités : décompte de contrôle indisponible (%s)", e)
        won = None
    if won is not None:
        etat["gagnees_nt360"] = won
        etat["complet"] = gagnees == won
        if gagnees != won:
            logger.warning("nt360 opportunités : %d gagnées lues pour %d annoncées par nt360", gagnees, won)
    return etat


# ── Synchro d'une ressource ─────────────────────────────────────────────────

async def _sync_ressource(adapter: Nt360Adapter, session_factory, res: Ressource, ctx) -> dict:
    lectures = [("", await adapter.fetch_all(res.nom))]
    if res.par_entite:
        for entite in ENTITES:
            lectures.append((entite, await adapter.fetch_all(res.nom, entite=entite)))
    rows = []
    for entite, lecture in lectures:
        for item in lecture.items:
            for r in res.correspondance(item, ctx):
                rows.append({**r, "entite": entite} if res.par_entite else r)
    liste = Nt360Liste(
        items=[i for _, lecture in lectures for i in lecture.items],
        pages=sum(lecture.pages for _, lecture in lectures),
        complete=all(lecture.complete for _, lecture in lectures),
    )
    etat = {"recus": len(liste.items), "lignes": len(rows), "pages": liste.pages}

    if not liste.complete:
        logger.warning("nt360 %s : liste incomplète, table conservée en l'état", res.nom)
        return {**etat, "statut": "conservee", "motif": "liste incomplète"}

    async with session_factory() as session:
        existantes = await session.scalar(select(func.count()).select_from(res.table))
        if not rows and existantes and not res.vide_autorise:
            logger.warning("nt360 %s : réponse vide, %d ligne(s) existante(s) conservée(s)", res.nom, existantes)
            return {**etat, "statut": "conservee", "motif": "réponse vide"}
        maintenant = datetime.utcnow()
        await session.execute(delete(res.table))
        session.add_all(res.table(**r, synced_at=maintenant) for r in rows)
        await session.commit()
    if rows and not existantes:
        # Le signal attendu pour les ressources en attente de droits.
        logger.info("nt360 %s : première alimentation (%d ligne(s))", res.nom, len(rows))
        etat["premiere_alimentation"] = True
    elif not rows and res.facultative:
        etat["vide"] = True
    return {**etat, "statut": "ok"}


# ── Objectifs nt360 → commercial_objectives ─────────────────────────────────

async def _appliquer_objectifs(session_factory) -> dict:
    """Reporte les objectifs nt360 de périmètre global en objectifs d'équipe.

    Une ligne par entité (`scope_ref` = filiale) : `objectifs.py` additionne
    toutes les lignes `equipe` de l'année, et le miroir Odoo couvre le groupe
    (CA 2026 miroir ≈ overview_2026 nt360 toutes entités), donc la somme des
    entités est le bon total à comparer.

    Règles :
    - un objectif d'équipe SAISI À LA MAIN pour l'année l'emporte : nt360 ne
      s'ajoute pas à côté (sinon objectifs.py additionnerait les deux) ;
    - une révision n'est créée que si la cible change — jamais d'écrasement,
      conformément au contrat de révisions de commercial_objectives ;
    - les autres périmètres nt360 (par commercial, par BU…) ne sont pas
      reportés : il faudrait d'abord résoudre `scopeValue` vers un salesperson_id.
    """
    rapport = {"crees": 0, "inchanges": 0, "ignores_manuel": 0, "ignores_perimetre": 0}
    async with session_factory() as session:
        objectifs = (await session.scalars(select(Nt360ObjectifModel))).all()
        manuels_par_annee: dict[int, bool] = {}

        for o in objectifs:
            if o.scope != "global" or o.target_cas <= 0:
                rapport["ignores_perimetre"] += 1
                continue
            annee = o.fiscal_year
            if annee not in manuels_par_annee:
                manuels_par_annee[annee] = bool(await session.scalar(
                    select(func.count()).select_from(CommercialObjectiveModel).where(
                        CommercialObjectiveModel.scope == "equipe",
                        CommercialObjectiveModel.kind == "ca",
                        CommercialObjectiveModel.period_type == "annee",
                        CommercialObjectiveModel.period_year == annee,
                        CommercialObjectiveModel.superseded.is_(False),
                        CommercialObjectiveModel.created_by != AUTEUR_OBJECTIFS,
                    )
                ))
                if manuels_par_annee[annee]:
                    logger.warning(
                        "nt360 objectifs %d : un objectif d'équipe saisi à la main existe, "
                        "les objectifs nt360 ne sont pas reportés", annee,
                    )
            if manuels_par_annee[annee]:
                rapport["ignores_manuel"] += 1
                continue

            ref = o.filiale or "groupe"
            cle = (
                CommercialObjectiveModel.scope == "equipe",
                CommercialObjectiveModel.scope_ref == ref,
                CommercialObjectiveModel.kind == "ca",
                CommercialObjectiveModel.period_type == "annee",
                CommercialObjectiveModel.period_year == annee,
                CommercialObjectiveModel.period_index == 0,
            )
            actifs = (await session.scalars(
                select(CommercialObjectiveModel).where(*cle, CommercialObjectiveModel.superseded.is_(False))
            )).all()
            if any(abs(a.target_amount_xof - o.target_cas) < 0.5 for a in actifs):
                rapport["inchanges"] += 1
                continue

            revision = (await session.scalar(
                select(func.max(CommercialObjectiveModel.revision)).where(*cle)
            )) or 0
            for a in actifs:
                a.superseded = True
            session.add(CommercialObjectiveModel(
                scope="equipe", scope_ref=ref, kind="ca", period_type="annee", period_year=annee,
                period_index=0, target_amount_xof=o.target_cas, target_count=0,
                revision=revision + 1, superseded=False,
                note=f"nt360:{o.id}", created_by=AUTEUR_OBJECTIFS, created_at=datetime.utcnow(),
            ))
            rapport["crees"] += 1
        await session.commit()
    if rapport["crees"]:
        logger.info("nt360 objectifs : %d révision(s) créée(s)", rapport["crees"])
    return rapport


# ── Point d'entrée ──────────────────────────────────────────────────────────

def _save_status(rapport: dict):
    try:
        _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATUS_FILE.write_text(json.dumps(rapport, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("Impossible de sauvegarder %s : %s", _STATUS_FILE.name, e)


async def run_nt360_sync(adapter: Nt360Adapter | None, session_factory=AsyncSessionLocal,
                         save_status: bool = True, rebaser_indicateurs: bool = True,
                         forcer_recuperation: bool = False) -> dict:
    if adapter is None:
        logger.info("Synchro nt360 ignorée : NT360_API_KEY absente")
        return {"statut": "desactivee"}

    debut = datetime.utcnow()
    rapport: dict = {"debut": debut.isoformat(), "ressources": {}, "statut": "ok"}
    ctx: dict = {"fps_exclus": set()}
    commandes_ok = False

    # Entité de chaque commande, lue avant les commandes qui la portent.
    try:
        ctx["entite_par_fp"], etat_entites = await _entites_commandes(adapter, session_factory)
        repartition = {e: sum(1 for v in ctx["entite_par_fp"].values() if v == e) for e in ENTITES}
        rapport["entites"] = {"statut": etat_entites, **repartition}
    except Nt360AuthError as e:
        logger.error("Synchro nt360 interrompue : %s", e)
        rapport.update(statut="cle_refusee", entites={"statut": "erreur", "motif": str(e)})
        if save_status:
            _save_status(rapport)
        return rapport

    for res in RESSOURCES:
        if res.depend_commandes and not commandes_ok:
            # Sans la liste des FP exclus, on risquerait d'écrire les jalons/BC
            # d'un partenaire intra-groupe : on garde l'état précédent.
            rapport["ressources"][res.nom] = {"statut": "conservee", "motif": "commandes indisponibles"}
            continue
        try:
            etat = await _sync_ressource(adapter, session_factory, res, ctx)
            if res.nom == "commandes":
                # Même conservée (liste incomplète), la lecture a rempli fps_exclus
                # sur ce qu'elle a vu ; seule une lecture complète la rend sûre.
                commandes_ok = etat["statut"] == "ok"
        except Nt360AuthError as e:
            if res.facultative and e.status_code == 403:
                # Droit non accordé sur cette ressource : on la retentera au
                # prochain passage, sans priver les autres de leur synchro.
                logger.info("nt360 %s : non autorisée pour cette clé (403)", res.nom)
                etat = {"statut": "non_autorisee", "motif": str(e)}
            else:
                logger.error("Synchro nt360 interrompue : %s", e)
                rapport["ressources"][res.nom] = {"statut": "erreur", "motif": str(e)}
                rapport["statut"] = "cle_refusee"
                break
        except Exception as e:
            logger.error("Synchro nt360 %s en échec : %s", res.nom, e, exc_info=True)
            etat = {"statut": "erreur", "motif": str(e)}
        rapport["ressources"][res.nom] = etat

    # Opportunités : après les commandes, dont elles tirent les N° FP à relire
    # et la liste des FP exclus.
    if rapport["statut"] == "ok":
        if not commandes_ok:
            rapport["ressources"]["opportunities"] = {"statut": "conservee", "motif": "commandes indisponibles"}
        else:
            try:
                rapport["ressources"]["opportunities"] = await _sync_opportunites(
                    adapter, session_factory, ctx, forcer_recuperation)
            except Nt360AuthError as e:
                logger.error("Synchro nt360 interrompue : %s", e)
                rapport["ressources"]["opportunities"] = {"statut": "erreur", "motif": str(e)}
                rapport["statut"] = "cle_refusee"
            except Exception as e:
                logger.error("Synchro nt360 opportunities en échec : %s", e, exc_info=True)
                rapport["ressources"]["opportunities"] = {"statut": "erreur", "motif": str(e)}

    if rapport["statut"] == "ok":
        try:
            rapport["objectifs_commerciaux"] = await _appliquer_objectifs(session_factory)
        except Exception as e:
            logger.error("nt360 : report des objectifs en échec : %s", e, exc_info=True)
            rapport["objectifs_commerciaux"] = {"statut": "erreur", "motif": str(e)}
        # « non_autorisee » est un état attendu (droits pas encore ouverts), pas un incident.
        if any(r.get("statut") not in ("ok", "non_autorisee") for r in rapport["ressources"].values()):
            rapport["statut"] = "partiel"

        # Les vues commandé/facturé viennent de passer (ou sont) sur nt360 : on
        # rebase une fois l'historique des indicateurs du briefing, sans quoi
        # le delta comparerait du HT nt360 à du TTC Odoo. Idempotent (marqueur).
        res = rapport["ressources"]
        if rebaser_indicateurs and all(res.get(r, {}).get("statut") == "ok" for r in ("commandes", "factures", "bc")):
            try:
                from modules.uc_briefing import indicateurs
                rebase = await indicateurs.assurer_base_nt360()
                if rebase is not None:
                    rapport["indicateurs_rebases"] = rebase
            except Exception as e:
                logger.error("nt360 : rebase de l'historique des indicateurs en échec : %s", e, exc_info=True)

        # Le pipeline vient de passer (ou est) sur nt360 : on date la bascule une
        # fois, pour que les comparaisons de snapshots ne la traversent jamais.
        if rebaser_indicateurs and res.get("opportunities", {}).get("statut") == "ok":
            try:
                from modules.uc_briefing import bascule
                depuis = await bascule.basculer_opportunites()
                if depuis is not None:
                    rapport["bascule_opportunites"] = depuis.isoformat()
            except Exception as e:
                logger.error("nt360 : datation de la bascule du pipeline en échec : %s", e, exc_info=True)

    rapport["fps_exclus"] = len(ctx["fps_exclus"])
    rapport["duree_s"] = round((datetime.utcnow() - debut).total_seconds(), 1)
    logger.info(
        "Synchro nt360 %s en %.1f s : %s", rapport["statut"], rapport["duree_s"],
        ", ".join(f"{k}={v.get('lignes', v['statut'])}" for k, v in rapport["ressources"].items()),
    )
    if save_status:
        _save_status(rapport)
    return rapport
