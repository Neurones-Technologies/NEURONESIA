import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
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
from db.models import ModulePermissionModel, UserModel

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
    await session.commit()
    await session.refresh(new_user)
    logger.info("Nouvel utilisateur créé : %s (%s) par %s", new_user.email, new_user.role, current_user.email)
    return _admin_user_payload(new_user)


@router.get("/users")
async def list_users(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Liste les utilisateurs (admin uniquement)."""
    _require_admin(current_user)

    result = await session.execute(select(UserModel).order_by(UserModel.created_at))
    users = result.scalars().all()
    return [_admin_user_payload(u) for u in users]


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

    if body.email is not None:
        email = body.email.lower().strip()
        if not email or "@" not in email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email invalide")
        if email != user.email:
            existing = await session.execute(select(UserModel).where(UserModel.email == email))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé")
            user.email = email

    if body.full_name is not None:
        user.full_name = body.full_name.strip()

    if body.role is not None:
        user.role = _validate_role(body.role)

    if body.is_active is not None:
        user.is_active = body.is_active

    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe trop court (6 caractères minimum)",
            )
        user.hashed_password = hash_password(body.password)

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
    if row:
        row.allowed = body.allowed
        row.updated_at = datetime.now(timezone.utc)
    else:
        session.add(ModulePermissionModel(view=view, role=role, allowed=body.allowed))
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

    from sqlalchemy import delete

    await session.execute(delete(ModulePermissionModel))
    await session.commit()
    invalidate_permissions_cache()

    logger.info("Matrice de permissions réinitialisée par %s", current_user.email)
    return await _matrix_payload(session)
