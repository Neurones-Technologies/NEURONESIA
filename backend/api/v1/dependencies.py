import logging
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.auth.jwt_adapter import decode_token
from core.domain.user import User, UserRole
from core.services import perimetre
from core.services.entites import ENTITES
from db.database import get_session
from db.models import UserModel

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)

# Cache JWT user 60s — évite un SELECT à chaque requête (dashboard + chat = 5-15 requêtes/session)
_user_cache: dict[int, tuple[User, float]] = {}
_USER_CACHE_TTL = 60.0


def _get_cached_user(user_id: int) -> User | None:
    import time
    entry = _user_cache.get(user_id)
    if entry and time.monotonic() - entry[1] < _USER_CACHE_TTL:
        return entry[0]
    _user_cache.pop(user_id, None)
    return None


def _cache_user(user_id: int, user: User) -> None:
    import time
    _user_cache[user_id] = (user, time.monotonic())
    # Éviter croissance illimitée
    if len(_user_cache) > 1024:
        oldest = min(_user_cache, key=lambda k: _user_cache[k][1])
        _user_cache.pop(oldest, None)


def invalidate_user_cache(user_id: int | None = None) -> None:
    """Purge le cache utilisateur après une modification (rôle, statut, etc.).

    Sans argument, purge tout le cache. Indispensable après un PATCH admin :
    sinon l'utilisateur modifié garde son ancien rôle jusqu'à 60 s.
    """
    if user_id is None:
        _user_cache.clear()
    else:
        _user_cache.pop(user_id, None)


# Rôles toujours au niveau groupe : le DG pilote les trois entités (son cockpit
# garde son propre sélecteur, cf. briefing ?pays=), l'admin administre tout.
_ROLES_GROUPE = {"dg", "admin"}


def poser_perimetre(user: User, pays_demande: str | None = None) -> str | None:
    """Fixe l'entité imposée à la requête en cours (core/services/perimetre.py).

    - DG / admin : groupe, toujours ;
    - compte rattaché à un pays : CE pays, quoi que demande l'appelant — un
      en-tête ou une URL modifiée ne lui ouvre pas les autres pays ;
    - compte groupe : le pays choisi dans le sélecteur (en-tête X-Pays), sinon
      le groupe.
    Rend l'entité posée (None = groupe).
    """
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role in _ROLES_GROUPE:
        entite = None
    elif user.pays:
        entite = user.pays if user.pays in ENTITES else None
    else:
        demande = (pays_demande or "").strip().upper()
        entite = demande if demande in ENTITES else None
    perimetre.definir(entite)
    return entite


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: AsyncSession = Depends(get_session),
    x_pays: Annotated[str | None, Header(alias="X-Pays")] = None,
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expiré")
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")

    cached = _get_cached_user(user_id)
    if cached is not None:
        poser_perimetre(cached, x_pays)
        return cached

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user_row = result.scalar_one_or_none()

    if not user_row or not user_row.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable ou désactivé")

    try:
        role = UserRole(user_row.role)
    except ValueError:
        # Rôle inconnu en base (donnée legacy) → accès minimal plutôt que 500
        logger.warning("Rôle inconnu '%s' pour %s — repli sur viewer", user_row.role, user_row.email)
        role = UserRole.VIEWER

    user = User(
        id=user_row.id,
        email=user_row.email,
        full_name=user_row.full_name,
        role=role,
        is_active=user_row.is_active,
        created_at=user_row.created_at,
        last_login=user_row.last_login,
        pays=user_row.pays or "",
    )
    _cache_user(user_id, user)
    poser_perimetre(user, x_pays)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_views(*views: str):
    """Dépendance de gating : l'utilisateur doit avoir accès à AU MOINS UNE des vues.

    Usage : @router.get(..., dependencies=[Depends(require_views("tresorerie"))])
    La matrice module × rôle est dynamique : défauts de config/permissions.py
    surchargés par la table module_permissions (écran Administration).
    """
    from config.permissions import can_access

    async def _check(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        for v in views:
            if await can_access(session, role, v):
                return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Accès refusé — rôle '{role}' non autorisé sur ce module",
        )

    return _check
