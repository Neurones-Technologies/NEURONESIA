"""Endpoints du briefing quotidien : lecture (section du rôle courant du
demandeur), statut, et relance manuelle. Le contenu est gelé par le job
planifié de minuit (backend/jobs/scheduler.py) — GET ne régénère jamais,
sauf absence totale de store (tout premier démarrage de l'application).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.v1.dependencies import CurrentUser
from modules.uc_briefing import preferences, service, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/briefing", tags=["Briefing"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _llm(request: Request):
    return getattr(request.app.state.container, "llm_sonnet", None)


def _role_of(current_user) -> str:
    role = current_user.role
    return role.value if hasattr(role, "value") else str(role)


def _require_role_scope(current_user, role: str) -> None:
    """La composition du débrief est PARTAGÉE par tous les porteurs d'un rôle :
    seul un porteur de ce rôle, ou l'admin, peut la modifier.

    La matrice module × rôle dit qui accède à l'ÉCRAN, jamais sur quel PÉRIMÈTRE
    on peut écrire — sans ce contrôle, un directeur commercial autorisé sur la
    vue « briefing » réécrirait le débrief de la direction générale. Même esprit
    que uc_arbitrage.router._require_mandate, admin exempté comme partout.
    """
    if role not in service.ROLES:
        raise HTTPException(status_code=404, detail=f"Rôle inconnu : {role}")
    actuel = _role_of(current_user)
    if actuel == "admin" or actuel == role:
        return
    raise HTTPException(
        status_code=403,
        detail=f"Le débrief du rôle « {role} » se règle depuis un compte de ce rôle.",
    )


@router.get("")
async def get_briefing(request: Request, current_user: CurrentUser):
    payload = store.load()
    if payload is None:
        # Tout premier démarrage : aucun run planifié n'a encore eu lieu.
        payload = await service.generate(_crm(request), _llm(request), triggered_by="cold_start")

    role = _role_of(current_user)
    section = payload.get("sections", {}).get(role)
    return {
        "generated_at": payload.get("generated_at"),
        "triggered_by": payload.get("triggered_by"),
        "role": role,
        "section": section,
    }


@router.get("/status")
async def briefing_status():
    payload = store.load()
    if payload is None:
        return {"generated_at": None, "triggered_by": None, "roles": [], "sections_en_echec": []}
    return {
        "generated_at": payload.get("generated_at"),
        "triggered_by": payload.get("triggered_by"),
        "roles": list(payload.get("sections", {}).keys()),
        "sections_en_echec": payload.get("sections_en_echec", []),
    }


@router.get("/preferences")
async def get_briefing_preferences(current_user: CurrentUser, role: str | None = None) -> dict:
    """Catalogue du rôle ET sélection courante. Sans `role`, celui du demandeur.

    Le catalogue voyage AVEC la sélection : le frontend ne détient pas de copie
    des libellés, qui divergerait dès la première évolution du catalogue, et n'a
    aucune règle de défaut à réimplémenter.
    """
    cible = role or _role_of(current_user)
    _require_role_scope(current_user, cible)
    pref = await preferences.load(cible)
    return {
        "role": cible,
        "elements": preferences.catalogue_pour(cible, pref["elements"]),
        "consigne": pref["consigne"],
        "consigne_max": preferences.CONSIGNE_MAX,
        "source": pref["source"],
        "updated_by": pref["updated_by"],
        "updated_at": pref["updated_at"],
    }


class BriefingPreferencesBody(BaseModel):
    role: str | None = None
    elements: list[str] = Field(default_factory=list)
    consigne: str = ""


@router.put("/preferences")
async def put_briefing_preferences(
    body: BriefingPreferencesBody, current_user: CurrentUser
) -> dict:
    """Remplace la composition d'un rôle.

    PUT et non PATCH : c'est la sélection entière qui est remplacée, pas une
    cellule (contrairement à la matrice de droits, modifiée case par case).

    N'entraîne AUCUNE régénération : appliquer les changements est un acte
    explicite et séparé (POST /refresh), sinon chaque case cochée coûterait deux
    appels LLM.
    """
    cible = body.role or _role_of(current_user)
    _require_role_scope(current_user, cible)

    connus = {e["id"] for e in preferences.catalogue_pour(cible)}
    inconnus = [e for e in body.elements if e not in connus]
    if inconnus:
        raise HTTPException(
            status_code=400,
            detail=f"Élément(s) inconnu(s) pour ce rôle : {', '.join(inconnus)}",
        )
    if not body.elements and not preferences.sanitize_consigne(body.consigne):
        # Rien de coché ET pas de consigne exploitable (une consigne faite
        # uniquement de balises <consigne> devient vide au nettoyage) : sans
        # puce ni boussole, narratif afficherait « Pas assez de données pour un
        # briefing aujourd'hui » sans que personne comprenne que c'est un
        # réglage qui l'a provoqué. Rien de coché AVEC une consigne est en
        # revanche accepté — mode « consigne pilote », où l'IA pioche dans tout
        # le pool de faits du rôle ce qui répond à la consigne
        # (cf. service._composition_depuis).
        raise HTTPException(
            status_code=400,
            detail=(
                "Cochez au moins un élément, ou rédigez une consigne : sans l'un "
                "ni l'autre, le débrief n'aurait rien à raconter."
            ),
        )

    saved = await preferences.save(
        cible, body.elements, body.consigne, updated_by=current_user.email
    )
    logger.info(
        "Composition du débrief '%s' réglée par %s : %d élément(s), consigne %s%s",
        cible, current_user.email, len(saved["elements"]), "posée" if saved["consigne"] else "vide",
        " (mode consigne pilote)" if not saved["elements"] and saved["consigne"] else "",
    )
    return {
        "role": cible,
        "elements": preferences.catalogue_pour(cible, saved["elements"]),
        "consigne": saved["consigne"],
        "consigne_max": preferences.CONSIGNE_MAX,
        "source": saved["source"],
        "updated_by": saved["updated_by"],
        "updated_at": saved["updated_at"],
    }


@router.post("/refresh")
async def refresh_briefing(request: Request, current_user: CurrentUser, role: str | None = None):
    """Relance manuelle. Avec `role` — ou pour un non-admin — cette seule section ;
    sans `role` et en admin, les cinq (comportement historique).

    Le contrôle d'identité n'existait pas ici : tout porteur de la vue
    « briefing » pouvait déclencher 5 rôles × 2 appels LLM en boucle. Un
    non-admin est désormais borné à sa propre section.
    """
    if role is None and _role_of(current_user) == "admin":
        payload = await service.generate(_crm(request), _llm(request), triggered_by="manual")
        return {
            "scope": "all",
            "generated_at": payload.get("generated_at"),
            "roles": list(payload.get("sections", {}).keys()),
            "sections_en_echec": payload.get("sections_en_echec", []),
        }

    cible = role or _role_of(current_user)
    _require_role_scope(current_user, cible)
    section = await service.generate_role(cible, _crm(request), _llm(request), triggered_by="manual")
    return {
        "scope": "role",
        "role": cible,
        "generated_at": section.get("generated_at"),
        "nb_puces": len(section.get("bullets", [])),
    }
