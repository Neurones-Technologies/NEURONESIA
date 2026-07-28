from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"
    # Personas métier du cockpit (alignés sur le frontend)
    DG = "dg"
    DIR_COMMERCIAL = "dir_commercial"
    DIR_OPERATIONS = "dir_operations"
    PRESALE = "presale"
    DIR_FINANCIER = "dir_financier"
    COMMERCIAL = "commercial"


@dataclass
class User:
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login: datetime | None = None
