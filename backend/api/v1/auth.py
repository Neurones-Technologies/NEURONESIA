import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.auth.jwt_adapter import create_access_token, hash_password, verify_password
from api.v1.dependencies import get_current_user, invalidate_user_cache
from config.rate_limit import limiter
from config.permissions import (
    DEFAULT_MODULE_ACCESS,
    EDITABLE_ROLES,
    PERSONA_ROLES,
    allowed_views,
    get_module_access,
    invalidate_permissions_cache,
)
from core.domain.user import User, UserRole
from db.database import get_session
from db.models import (
    AdminAuditModel,
    ArbitrageContexteModel,
    ArbitrageParamModel,
    BriefingPreferenceModel,
    CommercialParamModel,
    ConversationModel,
    DecisionModel,
    ModulePermissionModel,
    UserModel,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: str = "user"


class UpdateUserRequest(BaseModel):
    """Tous les champs sont optionnels — seuls ceux fournis sont modifiés."""
    email: str | None = None
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


_VALID_ROLES = {r.value for r in UserRole}


def _require_admin(current_user: User) -> None:
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux admins")


def _validate_role(role: str) -> str:
    role = role.strip().lower()
    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rôle inconnu : {role} (valides : {', '.join(sorted(_VALID_ROLES))})",
        )
    return role


def _user_payload(user: UserModel, views: list[str] | None) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        # None = accès total (admin) — le front filtre sa sidebar avec cette liste
        "allowed_views": views,
    }


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")  # ≈10/minute réel cumulé sur les 2 workers — voir config/rate_limit.py
async def login(
    request: Request, body: LoginRequest, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(UserModel).where(UserModel.email == body.email.lower().strip())
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé",
        )

    user.last_login = datetime.now(timezone.utc)
    await session.commit()

    token = create_access_token(user.id, user.email, user.role)
    logger.info("Login réussi — %s (%s)", user.email, user.role)

    views = await allowed_views(session, user.role)
    return LoginResponse(access_token=token, user=_user_payload(user, views))


@router.get("/me")
async def me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": role,
        "allowed_views": await allowed_views(session, role),
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
    }


@router.post("/logout")
async def logout():
    # Avec JWT stateless, le logout se fait côté client (suppression du token)
    return {"message": "Déconnecté"}


def _admin_user_payload(u: UserModel) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# ---------- Journal d'administration ----------
#
# Les endpoints ci-dessous ne laissaient qu'un `logger.info` : la trace vivait
# dans les logs du serveur, illisible depuis l'application et perdue à la
# rotation. Une désactivation ou une suppression de compte doit pouvoir se
# relire — c'est ce que porte `admin_audit`.

AUDIT_USER_CREATE = "user.create"
AUDIT_USER_UPDATE = "user.update"
AUDIT_USER_DELETE = "user.delete"
AUDIT_PERMISSION_UPDATE = "permission.update"
AUDIT_PERMISSION_RESET = "permission.reset"

_AUDIT_LIMIT_MAX = 200


def _audit(
    session: AsyncSession,
    actor: User,
    action: str,
    *,
    target_email: str = "",
    target_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Ajoute une ligne au journal — SANS commit.

    Le commit reste celui de l'appelant, délibérément : la trace et l'action
    qu'elle décrit partagent alors la même transaction. Une écriture qui échoue
    ne laisse donc pas de ligne annonçant un changement qui n'a pas eu lieu, et
    une action réussie ne peut pas passer inaperçue.
    """
    session.add(
        AdminAuditModel(
            at=datetime.now(timezone.utc),
            actor_email=actor.email,
            action=action,
            target_email=target_email,
            target_id=target_id,
            details=details or {},
        )
    )


def _audit_payload(row: AdminAuditModel) -> dict:
    return {
        "id": row.id,
        "at": row.at.isoformat() if row.at else None,
        "actor_email": row.actor_email,
        "action": row.action,
        "target_email": row.target_email,
        "target_id": row.target_id,
        "details": row.details or {},
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Crée un utilisateur (admin uniquement)."""
    _require_admin(current_user)

    email = body.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email invalide")
    if len(body.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe trop court (6 caractères minimum)",
        )
    role = _validate_role(body.role)

    existing = await session.execute(select(UserModel).where(UserModel.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé")

    new_user = UserModel(
        email=email,
        full_name=body.full_name.strip(),
        hashed_password=hash_password(body.password),
        role=role,
    )
    session.add(new_user)
    # `flush` avant l'audit : la ligne du journal porte l'id du compte créé, que
    # l'autoincrement n'attribue qu'à l'insertion.
    await session.flush()
    _audit(
        session,
        current_user,
        AUDIT_USER_CREATE,
        target_email=new_user.email,
        target_id=new_user.id,
        details={"role": new_user.role, "full_name": new_user.full_name},
    )
    await session.commit()
    await session.refresh(new_user)
    logger.info("Nouvel utilisateur créé : %s (%s) par %s", new_user.email, new_user.role, current_user.email)
    return _admin_user_payload(new_user)


@router.get("/users")
async def list_users(
    q: str | None = Query(None, description="Recherche sur l'email ou le nom complet"),
    role: str | None = Query(None, description="Filtre sur un rôle exact"),
    actif: bool | None = Query(None, description="true = comptes actifs, false = désactivés"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Liste les utilisateurs (admin uniquement), filtrable.

    Les filtres sont appliqués ici et non à l'écran : la liste doit rester
    utilisable quand elle dépasse ce qu'une page peut porter, et un filtre
    seulement visuel laisserait croire à un périmètre qu'il ne garantit pas.

    `total` compte l'effectif COMPLET, indépendamment des filtres — sans lui,
    « 3 comptes » après filtrage se lirait comme « 3 comptes en tout ».
    `admins_actifs` sert l'écran : c'est ce compteur qui dit si la prochaine
    rétrogradation touchera le dernier administrateur, garde-fou que le serveur
    applique de toute façon (cf. `_count_other_active_admins`).
    """
    _require_admin(current_user)

    stmt = select(UserModel)
    if q:
        motif = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(UserModel.email).like(motif),
                func.lower(UserModel.full_name).like(motif),
            )
        )
    if role:
        stmt = stmt.where(UserModel.role == _validate_role(role))
    if actif is not None:
        stmt = stmt.where(UserModel.is_active.is_(actif))

    result = await session.execute(stmt.order_by(UserModel.created_at))
    users = result.scalars().all()

    # Les compteurs sont TOUJOURS calculés sur l'effectif complet, jamais sur la
    # page filtrée : un bandeau qui suit le filtre annoncerait « 1 compte actif »
    # sur une recherche à un résultat.
    async def _compte(*conditions) -> int:
        return await session.scalar(
            select(func.count()).select_from(UserModel).where(*conditions)
        ) or 0

    return {
        "users": [_admin_user_payload(u) for u in users],
        "total": await _compte(),
        "actifs": await _compte(UserModel.is_active.is_(True)),
        # Un compte créé et jamais utilisé n'est pas un compte inactif : c'est un
        # accès ouvert que personne ne surveille.
        "jamais_connectes": await _compte(UserModel.last_login.is_(None)),
        "admins_actifs": await _compte(
            UserModel.role == UserRole.ADMIN.value, UserModel.is_active.is_(True)
        ),
        "roles": PERSONA_ROLES,
    }


# ---------- Fiche détaillée d'un compte (admin uniquement) ----------
#
# La liste répond « qui a un compte ». Elle ne répond pas aux questions qui
# décident réellement d'une désactivation ou d'un changement de rôle : ce compte
# sert-il ? à quoi ? qu'a-t-il produit ? La fiche les instruit, et le fait
# UNIQUEMENT à partir d'état serveur déjà écrit — aucune table n'a été créée
# pour elle. Trois sources, trois lectures :
#
#   - le PÉRIMÈTRE vient de `allowed_views`, la fonction même qu'appliquent les
#     dépendances de chaque endpoint (cf. main.py::require_views). Ce n'est donc
#     pas une reconstitution parallèle des droits, c'est la lecture de l'unique
#     règle en vigueur.
#   - l'ACTIVITÉ vient de `conversations` (Copilote), la seule table qui porte un
#     `user_id`. Elle dit si le compte est vivant, et depuis quels profils.
#   - l'EMPREINTE vient des colonnes `created_by` / `updated_by` semées dans les
#     modules métier. Elles portent l'email, pas l'id : un compte supprimé laisse
#     donc ses traces derrière lui, et renommer un email les détache. C'est une
#     limite du schéma existant, pas de cette lecture — la fiche s'en tient à ce
#     qui est effectivement attribuable.

# Tables de réglage qui nomment leur dernier auteur. Le troisième élément est le
# champ qui identifie la ligne, différent d'une table à l'autre.
_REGLAGES_TRACES = (
    (BriefingPreferenceModel, "Composition du débrief", "role"),
    (ArbitrageParamModel, "Conditions d'arbitrage", "key"),
    (CommercialParamModel, "Paramètres commerciaux", "key"),
)


async def _empreinte_reglages(session: AsyncSession, email: str) -> list[dict]:
    """Réglages dont ce compte est le dernier auteur connu.

    « Dernier auteur » et non « auteur » : ces tables ne gardent qu'un
    `updated_by`, écrasé à chaque écriture. Un réglage modifié puis re-modifié
    par quelqu'un d'autre sort donc de cette liste — elle dit ce qui porte
    aujourd'hui la signature du compte, pas tout ce qu'il a jamais touché.
    """
    lignes: list[dict] = []
    for model, libelle, champ in _REGLAGES_TRACES:
        result = await session.execute(select(model).where(model.updated_by == email))
        for row in result.scalars():
            lignes.append(
                {
                    "objet": libelle,
                    "cle": getattr(row, champ, ""),
                    "at": row.updated_at.isoformat() if row.updated_at else None,
                }
            )
    lignes.sort(key=lambda ligne: ligne["at"] or "", reverse=True)
    return lignes


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Fiche détaillée d'un compte : périmètre effectif, activité, empreinte, journal."""
    _require_admin(current_user)

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    email = user.email

    # ── Périmètre effectif ────────────────────────────────────────────────────
    views = await allowed_views(session, user.role)
    matrix = await get_module_access(session)
    autorisees = None if views is None else set(views)
    modules = [
        {"view": view, "allowed": autorisees is None or view in autorisees}
        for view in matrix
    ]

    # ── Activité (Copilote) ───────────────────────────────────────────────────
    # `role == "user"` isole les QUESTIONS posées : la table porte aussi les
    # réponses de l'assistant, qui doubleraient le compte sans rien dire de
    # l'usage fait du compte.
    nb_questions = await session.scalar(
        select(func.count())
        .select_from(ConversationModel)
        .where(ConversationModel.user_id == user_id, ConversationModel.role == "user")
    ) or 0
    derniere_question = await session.scalar(
        select(func.max(ConversationModel.created_at)).where(
            ConversationModel.user_id == user_id,
            ConversationModel.role == "user",
        )
    )
    profils_result = await session.execute(
        select(ConversationModel.profile, func.count())
        .where(ConversationModel.user_id == user_id, ConversationModel.role == "user")
        .group_by(ConversationModel.profile)
        .order_by(func.count().desc())
    )
    profils = [
        {"profile": profile or "—", "questions": n} for profile, n in profils_result.all()
    ]

    # ── Empreinte métier ──────────────────────────────────────────────────────
    decisions_creees = await session.scalar(
        select(func.count()).select_from(DecisionModel).where(DecisionModel.created_by == email)
    ) or 0
    decisions_tranchees = await session.scalar(
        select(func.count())
        .select_from(DecisionModel)
        .where(DecisionModel.created_by == email, DecisionModel.status == "tranchee")
    ) or 0
    derniere_decision = await session.scalar(
        select(func.max(DecisionModel.created_at)).where(DecisionModel.created_by == email)
    )
    contextes = await session.scalar(
        select(func.count())
        .select_from(ArbitrageContexteModel)
        .where(ArbitrageContexteModel.created_by == email)
    ) or 0
    reglages = await _empreinte_reglages(session, email)

    # ── Journal, restreint à ce compte ────────────────────────────────────────
    journal_result = await session.execute(
        select(AdminAuditModel)
        .where(AdminAuditModel.target_email == email)
        .order_by(AdminAuditModel.at.desc(), AdminAuditModel.id.desc())
        .limit(20)
    )

    # `created_at` est stocké sans fuseau (colonne DateTime nue, comme partout
    # ailleurs dans ce schéma) : on le relit en UTC pour ne pas soustraire un
    # naïf d'un aware, ce qui lèverait.
    anciennete = (
        (datetime.now(timezone.utc) - user.created_at.replace(tzinfo=timezone.utc)).days
        if user.created_at
        else None
    )

    return {
        "compte": {
            **_admin_user_payload(user),
            "anciennete_jours": anciennete,
            # Un compte créé et jamais utilisé n'est pas un compte inactif : c'est
            # un accès ouvert que personne ne surveille. La distinction mérite
            # d'être servie explicitement plutôt que déduite d'un `last_login` nul.
            "jamais_connecte": user.last_login is None,
            # L'écran doit pouvoir dire « c'est votre compte » AVANT le clic : le
            # serveur refuse l'auto-suppression, autant ne pas la proposer.
            "est_moi": user.id == current_user.id,
        },
        "perimetre": {
            "is_admin": views is None,
            "modules": modules,
            "total": len(modules),
            "autorises": len(modules) if views is None else len(autorisees or set()),
        },
        "activite": {
            "questions_copilote": nb_questions,
            "derniere_question": derniere_question.isoformat() if derniere_question else None,
            "profils": profils,
        },
        "empreinte": {
            "decisions_creees": decisions_creees,
            "decisions_tranchees": decisions_tranchees,
            "derniere_decision": derniere_decision.isoformat() if derniere_decision else None,
            "contextes_renseignes": contextes,
            "reglages": reglages,
        },
        "journal": [_audit_payload(row) for row in journal_result.scalars()],
    }


@router.get("/audit")
async def list_audit(
    limit: int = Query(50, ge=1, le=_AUDIT_LIMIT_MAX),
    action: str | None = Query(None, description="Filtre sur un type d'action"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Journal d'administration, du plus récent au plus ancien (admin uniquement).

    Table en append seul : aucun endpoint n'écrit par-dessus ni ne purge. Le
    journal n'est pas modifiable depuis l'application — un journal qu'on peut
    corriger ne prouve rien.
    """
    _require_admin(current_user)

    stmt = select(AdminAuditModel)
    if action:
        stmt = stmt.where(AdminAuditModel.action == action.strip())
    result = await session.execute(
        stmt.order_by(AdminAuditModel.at.desc(), AdminAuditModel.id.desc()).limit(limit)
    )
    lignes = [_audit_payload(row) for row in result.scalars()]
    total = await session.scalar(select(func.count()).select_from(AdminAuditModel)) or 0
    return {"lignes": lignes, "total": total, "limit": limit}


async def _count_other_active_admins(session: AsyncSession, excluded_user_id: int) -> int:
    result = await session.execute(
        select(UserModel).where(
            UserModel.role == "admin",
            UserModel.is_active.is_(True),
            UserModel.id != excluded_user_id,
        )
    )
    return len(result.scalars().all())


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Modifie un utilisateur (admin uniquement) : nom, email, rôle, statut, mot de passe.

    Garde-fou : impossible de rétrograder ou désactiver le DERNIER admin actif
    (sinon plus personne ne peut administrer la plateforme).
    """
    _require_admin(current_user)

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    # Protection du dernier admin actif
    losing_admin = (
        user.role == "admin"
        and user.is_active
        and (
            (body.role is not None and _validate_role(body.role) != "admin")
            or body.is_active is False
        )
    )
    if losing_admin and await _count_other_active_admins(session, user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible : c'est le dernier compte admin actif",
        )

    # Le journal porte le DELTA, pas l'état complet : seuls les champs
    # effectivement modifiés, avec avant/après. Un PATCH qui ne change rien
    # (mêmes valeurs renvoyées) ne laisse donc aucune ligne — sinon le journal
    # se remplit d'entrées qui n'annoncent rien.
    changes: dict[str, dict] = {}

    if body.email is not None:
        email = body.email.lower().strip()
        if not email or "@" not in email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email invalide")
        if email != user.email:
            existing = await session.execute(select(UserModel).where(UserModel.email == email))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé")
            changes["email"] = {"avant": user.email, "apres": email}
            user.email = email

    if body.full_name is not None:
        nom = body.full_name.strip()
        if nom != user.full_name:
            changes["full_name"] = {"avant": user.full_name, "apres": nom}
            user.full_name = nom

    if body.role is not None:
        role = _validate_role(body.role)
        if role != user.role:
            changes["role"] = {"avant": user.role, "apres": role}
            user.role = role

    if body.is_active is not None:
        if body.is_active != user.is_active:
            changes["is_active"] = {"avant": user.is_active, "apres": body.is_active}
            user.is_active = body.is_active

    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe trop court (6 caractères minimum)",
            )
        # Le mot de passe est tracé comme un FAIT, jamais comme une valeur : ni en
        # clair, ni haché. Le journal doit dire qu'il a été réinitialisé, pas
        # offrir une seconde copie du secret à qui le lit.
        changes["password"] = {"reinitialise": True}
        user.hashed_password = hash_password(body.password)

    if changes:
        _audit(
            session,
            current_user,
            AUDIT_USER_UPDATE,
            target_email=user.email,
            target_id=user.id,
            details=changes,
        )

    await session.commit()
    await session.refresh(user)

    # L'utilisateur modifié ne doit pas garder son ancien rôle en cache JWT
    invalidate_user_cache(user.id)

    logger.info("Utilisateur %s modifié par %s", user.email, current_user.email)
    return _admin_user_payload(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Supprime définitivement un utilisateur (admin uniquement).

    Garde-fous : impossible de supprimer son propre compte, ni le dernier
    admin actif. Pour retirer l'accès sans perdre la trace du compte,
    préférer la désactivation (PATCH is_active=false).
    """
    _require_admin(current_user)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible de supprimer son propre compte",
        )

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    if (
        user.role == "admin"
        and user.is_active
        and await _count_other_active_admins(session, user.id) == 0
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible : c'est le dernier compte admin actif",
        )

    email = user.email
    # Tracé AVANT la suppression : après, il ne reste rien à décrire. La ligne du
    # journal survit au compte (`target_email` est une copie, pas une clé
    # étrangère) — c'est justement la suppression qu'il faut pouvoir relire.
    _audit(
        session,
        current_user,
        AUDIT_USER_DELETE,
        target_email=email,
        target_id=user_id,
        details={"role": user.role, "full_name": user.full_name, "is_active": user.is_active},
    )
    await session.delete(user)
    await session.commit()
    invalidate_user_cache(user_id)

    logger.info("Utilisateur %s SUPPRIMÉ par %s", email, current_user.email)
    return {"deleted": True, "id": user_id, "email": email}


# ---------- Matrice rôles × modules (admin uniquement) ----------


class PermissionUpdateRequest(BaseModel):
    view: str
    role: str
    allowed: bool


async def _matrix_payload(session: AsyncSession) -> dict:
    matrix = await get_module_access(session)
    return {"roles": PERSONA_ROLES, "views": list(matrix.keys()), "matrix": matrix}


@router.get("/permissions")
async def get_permissions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Matrice effective module × rôle (défauts + surcharges) — admin uniquement."""
    _require_admin(current_user)
    return await _matrix_payload(session)


@router.patch("/permissions")
async def update_permission(
    body: PermissionUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Modifie UNE cellule de la matrice (admin uniquement) — appliqué dès la requête suivante.

    Garde-fous : le rôle admin n'est pas modifiable, et un rôle doit conserver
    au moins une vue (sinon ses utilisateurs n'auraient plus aucun écran).
    """
    _require_admin(current_user)

    view = body.view.strip()
    role = body.role.strip().lower()
    if view not in DEFAULT_MODULE_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Module inconnu : {view}",
        )
    if role == UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'administrateur a toujours accès à tout — droits non modifiables",
        )
    if role not in EDITABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rôle inconnu : {role} (valides : {', '.join(EDITABLE_ROLES)})",
        )

    if not body.allowed:
        matrix = await get_module_access(session)
        remaining = [v for v, access in matrix.items() if access.get(role, False) and v != view]
        if not remaining:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Impossible : « {view} » est la dernière vue du rôle {role}",
            )

    result = await session.execute(
        select(ModulePermissionModel).where(
            ModulePermissionModel.view == view,
            ModulePermissionModel.role == role,
        )
    )
    row = result.scalar_one_or_none()
    avant = row.allowed if row else DEFAULT_MODULE_ACCESS[view].get(role, False)
    if row:
        row.allowed = body.allowed
        row.updated_at = datetime.now(timezone.utc)
    else:
        session.add(ModulePermissionModel(view=view, role=role, allowed=body.allowed))
    _audit(
        session,
        current_user,
        AUDIT_PERMISSION_UPDATE,
        details={"view": view, "role": role, "avant": avant, "apres": body.allowed},
    )
    await session.commit()
    invalidate_permissions_cache()

    logger.info(
        "Permission %s × %s → %s par %s",
        view, role, "autorisé" if body.allowed else "refusé", current_user.email,
    )
    return await _matrix_payload(session)


@router.post("/permissions/reset")
async def reset_permissions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Supprime toutes les surcharges → retour à la matrice par défaut du code."""
    _require_admin(current_user)

    # Le nombre de surcharges effacées est la seule chose qui rende cette ligne
    # de journal interprétable : « matrice réinitialisée » sur une table déjà
    # vide et sur douze cellules surchargées ne décrit pas le même geste.
    surcharges = await session.scalar(
        select(func.count()).select_from(ModulePermissionModel)
    ) or 0
    await session.execute(delete(ModulePermissionModel))
    _audit(
        session,
        current_user,
        AUDIT_PERMISSION_RESET,
        details={"surcharges_effacees": surcharges},
    )
    await session.commit()
    invalidate_permissions_cache()

    logger.info("Matrice de permissions réinitialisée par %s", current_user.email)
    return await _matrix_payload(session)
