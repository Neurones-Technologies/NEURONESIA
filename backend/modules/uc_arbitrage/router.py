"""Module Arbitrages — registre de décisions inter-profils.

Contrairement aux autres modules du cockpit, celui-ci n'existait dans aucun
mirroir Odoo ni dans le blueprint 25 modules d'origine : la « file
d'arbitrage » (dossiers ouverts) est calculée en recoupant des signaux déjà
produits par d'autres modules (impayés × cross-sell/renouvellement), et le
registre de décisions (module 28) persiste dans la table `decisions` — qui
contenait déjà une décision réelle avant ce module (cf. db/models.py).
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from api.v1.dependencies import CurrentUser
from modules.uc_arbitrage import aggregation, narratif, store
from modules.uc_crosssell.aggregation import build_montee_valeur

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/arbitrage", tags=["Arbitrages"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


def _require_mandate(current_user, mandat_role: str | None) -> None:
    """Le mandat (`dg` | `dir_financier`, cf. aggregation._mandat) est la seule
    autorité qui peut engager OU refermer un dossier. L'admin n'est jamais bloqué,
    comme partout ailleurs dans l'app. Un mandat vide (décisions antérieures à ce
    module, cf. le GO/NO-BID d'avant-vente) ne bloque personne : on ne verrouille
    pas rétroactivement des lignes qui n'ont jamais porté de mandat."""
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    mandat = (mandat_role or "").strip()
    if role != "admin" and mandat and role != mandat:
        raise HTTPException(
            status_code=403,
            detail=f"Cette décision relève du mandat « {mandat} », pas du vôtre.",
        )


async def _compute_candidates(request: Request) -> list[dict]:
    crm = _crm(request)
    unpaid = await crm.get_unpaid_exposure()
    lines = await crm.get_order_lines()
    crosssell = build_montee_valeur(lines)
    portfolio = await crm.get_client_portfolio(limit=200)
    portfolio_by_client = {c["client"]: c for c in portfolio}

    # Comportement de paiement réel des seuls débiteurs en retard (≤ 10 clients,
    # cf. top_10_debiteurs) — pas de tous les clients du miroir : chaque appel
    # scanne les factures d'un client, autant ne le faire que pour ceux qui
    # peuvent effectivement produire un dossier. Un appel qui échoue laisse son
    # dossier sans profil mesuré (classe `historique_insuffisant`) plutôt que de
    # faire tomber la file entière.
    debiteurs = [d for d in unpaid.get("top_10_debiteurs", []) if d.get("retard_max_jours", 0) > 0]
    collection_stats: dict[str, dict] = {}
    behaviour: dict[str, dict] = {}
    for debt in debiteurs:
        client = debt.get("client") or ""
        if not client or client == "—":
            continue
        try:
            collection_stats[client] = await crm.get_invoice_collection_stats(client_name=client)
            behaviour[client] = await crm.get_payment_behaviour(client_name=client)
        except Exception as exc:
            logger.warning("Comportement de paiement indisponible pour « %s » : %s", client, exc)

    return aggregation.detect_client_conflicts(
        unpaid.get("top_10_debiteurs", []), crosssell, portfolio_by_client, collection_stats, behaviour,
    )


@router.get("/file")
async def arbitrage_file(request: Request):
    """Module 26 — dossiers ouverts : conflits détectés en temps réel +
    décisions persistées non tranchées."""
    candidates = await _compute_candidates(request)
    open_decisions = await store.list_decisions(status="en_cours")

    now = datetime.utcnow()
    dossiers_ouverts = len(candidates) + len(open_decisions)
    enjeu_cumule = sum(d["enjeu_xof"] for d in candidates) + sum(d["enjeu_xof"] for d in open_decisions)
    cout_report = sum(d["cout_report_xof_semaine"] for d in candidates) + sum(d["cout_report_xof_semaine"] for d in open_decisions)
    # Échéance d'une décision ouverte = sa date butoir si elle en a une, sinon sa date
    # de relecture (posée d'office à la création depuis store.REVIEW_DELAY_DAYS). Les
    # dossiers non encore tranchés (`candidats`) n'ont, eux, aucune date : le miroir ne
    # contient aucune échéance contractuelle exploitable — cf. `echeance: "aucune"`.
    echeances = [d["due_date"] or d["review_date"] for d in open_decisions]
    echeances = [e for e in echeances if e]
    jours_echeance = None
    if echeances:
        prochaine = min(datetime.fromisoformat(e) for e in echeances)
        jours_echeance = max((prochaine - now).days, 0)
    revues_en_retard = sum(
        1 for d in open_decisions
        if d["review_date"] and datetime.fromisoformat(d["review_date"]) < now and not d["review_verdict"]
    )

    return {
        "kpi": {
            "dossiers_ouverts": dossiers_ouverts,
            "enjeu_cumule_m_fcfa": _m(enjeu_cumule),
            "echeance_plus_proche_jours": jours_echeance,
            "cout_report_m_fcfa_semaine": round(cout_report / 1_000_000, 1),
            "revues_en_retard": revues_en_retard,
            # Seuil au-delà duquel le mandat bascule à la DG (cf. aggregation._mandat) —
            # exposé pour que l'écran explique POURQUOI un dossier remonte à la DG plutôt
            # qu'à la direction dont vient le signal, au lieu de le laisser deviner.
            "seuil_mandat_dg_m_fcfa": _m(aggregation.ENJEU_MANDAT_DG_XOF),
        },
        "candidats": candidates,
        "decisions_ouvertes": open_decisions,
    }


@router.get("/dossier/{subject_ref}")
async def arbitrage_dossier(subject_ref: str, request: Request):
    """Module 27 — détail d'un dossier : positions réelles, options
    déterministes (dont l'échéancier calibré sur le comportement de paiement
    mesuré du client), avocat du contraire rédigé par le LLM."""
    candidates = await _compute_candidates(request)
    dossier = next((d for d in candidates if d["subject_ref"] == subject_ref), None)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Aucun dossier d'arbitrage actif pour « {subject_ref} »")

    options = aggregation.build_options(dossier)
    recommandee = next(o for o in options if o["recommandee"])
    llm = getattr(request.app.state.container, "llm_sonnet", None)
    decisions_liees = await store.list_decisions(subject_ref=subject_ref)
    contextes = await store.list_contextes(subject_ref)

    # L'avocat du contraire reçoit le profil de payeur ET les décisions déjà
    # prises sur ce client avec le verdict de leur revue : c'est ce qui rend
    # effective la promesse « la relecture recalibre les recommandations
    # suivantes », jusqu'ici affichée sans mécanisme derrière.
    contre = await narratif.build_counter_argument(llm, dossier, recommandee, decisions_liees)

    # L'option C existe déjà (chiffres calculés par payeur.echeancier) ; le modèle
    # n'y ajoute que sa formulation négociable.
    plan = dossier.get("echeancier")
    option_c = next((o for o in options if o["code"] == "C"), None)
    if plan and option_c:
        redaction = await narratif.write_echeancier(llm, dossier, plan)
        option_c["argumentaire"] = redaction["argumentaire"]
        option_c["redige_par"] = redaction["redige_par"]
        if redaction["titre"]:
            option_c["titre"] = redaction["titre"]

    dernier_contexte = contextes[0]["motif_retard"] if contextes else ""
    manque = aggregation.missing_info(dossier, dernier_contexte)

    return {
        **dossier,
        "options": options,
        "contre_arguments": contre,
        "manque": manque,
        "decisions_liees": decisions_liees,
        "contextes_terrain": contextes,
    }


@router.get("/dossier/{subject_ref}/contexte")
async def list_contexte(subject_ref: str):
    """Contributions terrain déjà déposées sur ce dossier (motif du retard, etc.)."""
    return await store.list_contextes(subject_ref)


@router.post("/dossier/{subject_ref}/contexte")
async def add_contexte(subject_ref: str, payload: dict, current_user: CurrentUser):
    """Dépose une contribution terrain sur un dossier.

    Volontairement SANS contrôle de mandat, contrairement aux décisions : le
    mandat conditionne le droit d'engager l'entreprise, pas celui d'apporter une
    information. C'est même l'inverse qu'il faut viser ici — l'account manager,
    qui n'a jamais le mandat, est le seul à connaître le motif réel d'un retard,
    et le dossier le lui demande explicitement (cf. `missing_info`).
    """
    motif = (payload.get("motif_retard") or "").strip()
    actif = (payload.get("dossier_toujours_actif") or "").strip()
    if not motif and not actif:
        raise HTTPException(status_code=422, detail="Une contribution vide n'apporte rien au dossier.")
    if actif and actif not in ("oui", "non", "incertain"):
        raise HTTPException(status_code=422, detail="Réponse attendue : oui, non ou incertain.")

    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    return await store.add_contexte(subject_ref, payload, created_by=current_user.email, created_role=role)


# Statuts qu'une décision peut recevoir à sa création. `reportee` et `escaladee`
# existaient en modèle et en libellés d'écran sans qu'aucun chemin ne permette de
# les atteindre : il n'y avait donc aucune façon de dire « je ne tranche pas
# aujourd'hui » — le cas le plus fréquent en comité. Un dossier reporté est
# journalisé comme tel, avec son motif, au lieu de rester un dossier oublié.
_STATUTS_CREATION = ("en_cours", "tranchee", "reportee", "escaladee")


@router.post("/decisions")
async def create_decision(payload: dict, current_user: CurrentUser):
    if not payload.get("title"):
        raise HTTPException(status_code=422, detail="Le titre de la décision est requis")

    status = (payload.get("status") or "en_cours").strip()
    if status not in _STATUTS_CREATION:
        raise HTTPException(
            status_code=422,
            detail=f"Statut « {status} » non recevable à la création (attendus : {', '.join(_STATUTS_CREATION)}).",
        )
    # Reporter ou escalader sans dire pourquoi ne laisse aucune trace exploitable
    # à la revue : la décision reste dans le registre sans qu'on puisse juger si
    # l'attente était fondée. Trancher, en revanche, porte déjà son sens dans
    # l'option retenue — le motif y reste facultatif.
    if status in ("reportee", "escaladee") and not (payload.get("motif_decision") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Un report ou une escalade doit porter son motif — sinon la revue ne peut pas le juger.",
        )

    _require_mandate(current_user, payload.get("mandat_role"))
    payload = {**payload, "status": status}
    return await store.create_decision(payload, created_by=current_user.email)


@router.get("/decisions")
async def list_decisions(status: str | None = None, subject_ref: str | None = None):
    """Module 28 — engagements et revues (historique complet, y compris les
    décisions antérieures à ce module)."""
    return await store.list_decisions(status=status, subject_ref=subject_ref)


@router.patch("/decisions/{decision_id}")
async def update_decision(decision_id: int, patch: dict, current_user: CurrentUser):
    # Même contrôle de mandat que create_decision : sans lui, n'importe quel profil
    # pouvait clôturer la revue d'une décision hors de son ressort — et comme c'est la
    # revue qui alimente le score de fiabilité, cela rendait ce score non probant.
    existing = await store.get_decision(decision_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Décision introuvable")
    _require_mandate(current_user, existing.get("mandat_role"))

    decision = await store.update_decision(decision_id, patch)
    if decision is None:
        raise HTTPException(status_code=404, detail="Décision introuvable")
    return decision


@router.get("/reliability")
async def reliability(request: Request):
    """Module 29 — fiabilité des recommandations, calculée sur le registre
    réel de décisions revues (pas de score fabriqué sans historique)."""
    return await store.reliability_stats()
