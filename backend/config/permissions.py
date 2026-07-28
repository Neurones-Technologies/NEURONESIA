"""
Matrice des droits module × rôle du cockpit — source de vérité serveur.

Chaque « vue » correspond à une route du frontend (app/(cockpit)/<view>/).
L'admin a toujours accès à tout. Les rôles legacy `user`/`viewer` reçoivent
un accès minimal en lecture (dashboard + clients).

DEFAULT_MODULE_ACCESS fige les droits par défaut dans le code ; les surcharges
décidées depuis l'écran Administration (PATCH /v1/auth/permissions) sont
persistées dans la table `module_permissions` et prennent le dessus cellule
par cellule. La matrice effective (défauts + surcharges) est mise en cache en
mémoire et invalidée à chaque modification.
"""
import time
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.user import UserRole

# Rôles persona affichables dans la matrice (l'ordre suit le frontend)
PERSONA_ROLES: list[str] = [
    UserRole.ADMIN.value,
    UserRole.DG.value,
    UserRole.DIR_COMMERCIAL.value,
    UserRole.DIR_OPERATIONS.value,
    UserRole.PRESALE.value,
    UserRole.DIR_FINANCIER.value,
    UserRole.COMMERCIAL.value,
]

# Rôles dont les droits sont modifiables (l'admin a toujours tout, jamais éditable)
EDITABLE_ROLES: list[str] = [r for r in PERSONA_ROLES if r != UserRole.ADMIN.value]

# view → {role → autorisé}. Défauts = copie fidèle de la matrice du mockup.
DEFAULT_MODULE_ACCESS: dict[str, dict[str, bool]] = {
    "briefing":      {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": True,  "commercial": True},
    "dashboard":     {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": True,  "commercial": True},
    "actions":       {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": False, "commercial": True},
    "forecast":      {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": False, "commercial": False},
    "tresorerie":    {"dg": True,  "dir_commercial": False, "dir_operations": False, "presale": False, "dir_financier": True,  "commercial": False},
    "performance":   {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": True,  "commercial": False},
    "veille":        {"dg": True,  "dir_commercial": True,  "dir_operations": False, "presale": True,  "dir_financier": False, "commercial": True},
    "veille-client": {"dg": False, "dir_commercial": True,  "dir_operations": False, "presale": False, "dir_financier": False, "commercial": True},
    "veille-ao":     {"dg": False, "dir_commercial": True,  "dir_operations": False, "presale": True,  "dir_financier": False, "commercial": False},
    "crosssell":     {"dg": False, "dir_commercial": True,  "dir_operations": False, "presale": False, "dir_financier": False, "commercial": True},
    "portefeuille":  {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": True,  "dir_financier": True,  "commercial": True},
    "presales":      {"dg": True,  "dir_commercial": False, "dir_operations": True,  "presale": True,  "dir_financier": False, "commercial": False},
    "offres":        {"dg": False, "dir_commercial": True,  "dir_operations": False, "presale": True,  "dir_financier": False, "commercial": True},
    "couts":         {"dg": False, "dir_commercial": True,  "dir_operations": True,  "presale": True,  "dir_financier": True,  "commercial": False},
    "workflow":      {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": True,  "commercial": False},
    "taches":        {"dg": False, "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": False, "commercial": True},
    "leads":         {"dg": False, "dir_commercial": True,  "dir_operations": False, "presale": True,  "dir_financier": False, "commercial": True},
    "clients":       {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": True,  "commercial": True},
    "partenaires":   {"dg": False, "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": False, "commercial": False},
    "pipeline":      {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": True,  "dir_financier": False, "commercial": True},
    "catalogue":     {"dg": False, "dir_commercial": True,  "dir_operations": True,  "presale": True,  "dir_financier": False, "commercial": True},
    "documents":     {"dg": False, "dir_commercial": False, "dir_operations": True,  "presale": False, "dir_financier": False, "commercial": False},
    "admin":         {"dg": False, "dir_commercial": False, "dir_operations": False, "presale": False, "dir_financier": False, "commercial": False},
    # Registre de décisions / arbitrages inter-profils (module cockpit ajouté après le
    # blueprint 25 modules) — ouvert aux 5 personas métier, pas à l'avant-vente.
    "arbitrage":     {"dg": True,  "dir_commercial": True,  "dir_operations": True,  "presale": False, "dir_financier": True,  "commercial": True},
}

# Accès minimal des rôles legacy (comptes existants non migrés)
_LEGACY_VIEWS: dict[str, list[str]] = {
    UserRole.USER.value: ["dashboard", "clients", "documents"],
    UserRole.VIEWER.value: ["dashboard"],
}

# ── Matrice effective (défauts + surcharges DB), cache mémoire ────────────────
# TTL court : garde-fou multi-workers ; dans le process qui modifie, le cache
# est invalidé immédiatement via invalidate_permissions_cache().
_matrix_cache: dict[str, dict[str, bool]] | None = None
_matrix_cache_at: float = 0.0
_MATRIX_CACHE_TTL = 30.0


def invalidate_permissions_cache() -> None:
    """À appeler après toute écriture dans module_permissions."""
    global _matrix_cache
    _matrix_cache = None


async def get_module_access(session: AsyncSession) -> dict[str, dict[str, bool]]:
    """Matrice effective : défauts du code surchargés par la table module_permissions."""
    global _matrix_cache, _matrix_cache_at
    if _matrix_cache is not None and time.monotonic() - _matrix_cache_at < _MATRIX_CACHE_TTL:
        return _matrix_cache

    from db.models import ModulePermissionModel  # import local — évite le cycle config ↔ db

    matrix = deepcopy(DEFAULT_MODULE_ACCESS)
    result = await session.execute(select(ModulePermissionModel))
    for row in result.scalars():
        # Ligne orpheline (vue renommée, rôle retiré) → ignorée plutôt que 500
        if row.view in matrix and row.role in EDITABLE_ROLES:
            matrix[row.view][row.role] = row.allowed

    _matrix_cache, _matrix_cache_at = matrix, time.monotonic()
    return matrix


async def allowed_views(session: AsyncSession, role: str) -> list[str] | None:
    """Vues autorisées pour un rôle. None = accès total (admin)."""
    if role == UserRole.ADMIN.value:
        return None
    if role in _LEGACY_VIEWS:
        return list(_LEGACY_VIEWS[role])
    matrix = await get_module_access(session)
    return [view for view, access in matrix.items() if access.get(role, False)]


async def can_access(session: AsyncSession, role: str, view: str) -> bool:
    views = await allowed_views(session, role)
    return views is None or view in views
