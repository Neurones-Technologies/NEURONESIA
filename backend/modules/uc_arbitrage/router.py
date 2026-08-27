"""Module Arbitrages — registre de décisions inter-profils.

Contrairement aux autres modules du cockpit, celui-ci n'existait dans aucun
mirroir Odoo ni dans le blueprint 25 modules d'origine : la « file
d'arbitrage » (dossiers ouverts) est calculée en recoupant des signaux déjà
produits par d'autres modules (impayés × cross-sell/renouvellement), et le
registre de décisions (module 28) persiste dans la table `decisions` — qui
contenait déjà une décision réelle avant ce module (cf. db/models.py).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from api.v1.dependencies import CurrentUser
from modules.uc_arbitrage import aggregation, conditions, narratif, service, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/arbitrage", tags=["Arbitrages"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _role(current_user) -> str:
    return current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)


def _require_decision_authority(current_user) -> None:
    """Trancher un dossier — ou refermer sa revue — relève de la seule Direction
    générale. L'admin n'est jamais bloqué, comme partout ailleurs dans l'app.

    Le mandat (`mandat_role`, cf. aggregation._mandat) portait auparavant ce droit :
    sous le seuil d'enjeu DG, il désigne la direction citée par le dossier
    (`dir_financier`, `dir_commercial`, `commercial`), qui pouvait donc engager
    l'entreprise. Il reste calculé, affiché en tête de dossier, journalisé avec la
    décision et utilisé pour ordonner la file — il dit quelle direction INSTRUIT le
    dossier et le porte en comité — mais il n'ouvre plus la journalisation : quel
    que soit le montant, la décision d'engager remonte à la DG. L'écran suit la
    même règle (`DossierPanel.peutTrancher`) et n'affiche le cockpit de décision
    que chez elle.

    Conséquence assumée sur les décisions antérieures à ce module (GO/NO-BID
    d'avant-vente, mandat vide) : leur revue se clôt désormais depuis la DG ou un
    compte admin, plus depuis le profil qui les avait créées."""
    role = _role(current_user)
    if role not in ("admin", "dg"):
        raise HTTPException(
            status_code=403,
            detail="Seule la Direction générale tranche un arbitrage ou clôt sa revue.",
        )


async def _compute_candidates(request: Request, subject_ref: str | None = None) -> list[dict]:
    return await service.compute_candidates(_crm(request), subject_ref=subject_ref)


@router.get("/file")
async def arbitrage_file(request: Request, current_user: CurrentUser):
    """Module 26 — dossiers ouverts : conflits détectés en temps réel +
    décisions persistées non tranchées.

    La liste est restreinte aux conditions d'entrée activées par le profil du
    demandeur (cf. `conditions.py`) ; les KPI, eux, restent ceux de la file
    entière — cf. `service.compute_file`."""
    return await service.compute_file(_crm(request), role=_role(current_user))


# ─── Conditions d'entrée en arbitrage ─────────────────────────────────────────


@router.get("/conditions")
async def get_conditions(request: Request, current_user: CurrentUser):
    """Catalogue des conditions, réglage de chaque profil, et effet mesuré sur
    la file réelle.

    `mesure.refs_par_condition` permet à l'écran de recalculer l'effet de
    n'importe quelle combinaison pendant que l'utilisateur coche, sans nouvel
    appel : sans ce compteur, le ET se découvre en vidant sa file.
    """
    role = _role(current_user)
    candidats, par_profil = await asyncio.gather(
        _compute_candidates(request),
        store.get_conditions_par_profil(),
    )
    return {
        "catalogue": conditions.catalogue_public(),
        "profil": role,
        # L'admin n'a pas de profil métier : il règle ceux des autres, il n'en a
        # pas pour lui-même (sa propre file n'est donc jamais filtrée).
        "profils_parametrables": list(conditions.PROFILS_PARAMETRABLES),
        "conditions_actives": par_profil.get(role, []),
        "par_profil": par_profil,
        "mesure": conditions.mesurer(candidats, par_profil.get(role, [])),
    }


@router.put("/conditions/{profil}")
async def update_conditions(profil: str, payload: dict, request: Request, current_user: CurrentUser):
    """Active / désactive les conditions d'un profil.

    Chacun règle SON profil ; l'admin règle n'importe lequel. Le réglage est
    attaché au profil et non à la personne : il vaut donc pour tous les
    utilisateurs qui portent ce rôle — l'écran le dit explicitement, faute de
    quoi on modifierait la file d'un collègue sans le savoir.
    """
    if profil not in conditions.PROFILS_PARAMETRABLES:
        raise HTTPException(status_code=404, detail=f"Profil « {profil} » inconnu.")

    role = _role(current_user)
    if role != "admin" and role != profil:
        raise HTTPException(
            status_code=403,
            detail="Ce réglage est celui d'un autre profil que le vôtre.",
        )

    codes = payload.get("codes")
    if not isinstance(codes, list):
        raise HTTPException(status_code=422, detail="`codes` doit être une liste de codes de conditions.")

    # Un code non implémenté n'est pas une erreur (il peut venir d'un écran plus
    # ancien que ce backend) mais il ne doit pas passer inaperçu : sans cette
    # trace, un réglage qui ne s'applique pas se diagnostique à l'aveugle.
    ignores = conditions.inconnus(codes)
    if ignores:
        logger.warning("Conditions d'arbitrage inconnues ignorées pour « %s » : %s", profil, ", ".join(ignores))

    par_profil = await store.set_conditions_profil(profil, codes, updated_by=current_user.email)
    candidats = await _compute_candidates(request)
    actives = par_profil.get(profil, [])
    return {
        "profil": profil,
        "conditions_actives": actives,
        "conditions_ignorees": ignores,
        "par_profil": par_profil,
        "mesure": conditions.mesurer(candidats, actives),
    }


@router.get("/dossier/{subject_ref}")
async def arbitrage_dossier(subject_ref: str, request: Request):
    """Module 27 — détail d'un dossier : positions réelles, options
    déterministes (dont l'échéancier calibré sur le comportement de paiement
    mesuré du client), avocat du contraire rédigé par le LLM."""
    candidates = await _compute_candidates(request, subject_ref=subject_ref)
    dossier = next((d for d in candidates if d["subject_ref"] == subject_ref), None)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Aucun dossier d'arbitrage actif pour « {subject_ref} »")

    options = aggregation.build_options(dossier)
    recommandee = next(o for o in options if o["recommandee"])
    llm = getattr(request.app.state.container, "llm_sonnet", None)
    decisions_liees, contextes = await asyncio.gather(
        store.list_decisions(subject_ref=subject_ref),
        store.list_contextes(subject_ref),
    )

    # Les deux parties rédigées partent ensemble et passent par le cache de
    # narration (cf. narratif.build_dossier_narration).
    #
    # L'avocat du contraire reçoit le profil de payeur ET les décisions déjà
    # prises sur ce client avec le verdict de leur revue : c'est ce qui rend
    # effective la promesse « la relecture recalibre les recommandations
    # suivantes », jusqu'ici affichée sans mécanisme derrière.
    #
    # L'option C existe déjà (chiffres calculés par payeur.echeancier) ; le modèle
    # n'y ajoute que sa formulation négociable.
    option_c = next((o for o in options if o["code"] == "C"), None)
    plan = dossier.get("echeancier") if option_c else None
    contre, redaction = await narratif.build_dossier_narration(
        llm, dossier, recommandee, decisions_liees, plan
    )
    if redaction and option_c:
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

    _require_decision_authority(current_user)
    payload = {**payload, "status": status}
    return await store.create_decision(payload, created_by=current_user.email)


@router.get("/decisions")
async def list_decisions(status: str | None = None, subject_ref: str | None = None):
    """Module 28 — engagements et revues (historique complet, y compris les
    décisions antérieures à ce module)."""
    return await store.list_decisions(status=status, subject_ref=subject_ref)


@router.patch("/decisions/{decision_id}")
async def update_decision(decision_id: int, patch: dict, current_user: CurrentUser):
    # Même contrôle que create_decision : sans lui, n'importe quel profil pouvait
    # clôturer la revue d'une décision qu'il n'avait pas le droit de prendre — et
    # comme c'est la revue qui alimente le score de fiabilité, cela rendait ce score
    # non probant. La décision est relue par l'autorité qui l'a prise, donc la DG.
    existing = await store.get_decision(decision_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Décision introuvable")
    _require_decision_authority(current_user)

    decision = await store.update_decision(decision_id, patch)
    if decision is None:
        raise HTTPException(status_code=404, detail="Décision introuvable")
    return decision


@router.get("/reliability")
async def reliability(request: Request):
    """Module 29 — fiabilité des recommandations, calculée sur le registre
    réel de décisions revues (pas de score fabriqué sans historique)."""
    return await store.reliability_stats()
