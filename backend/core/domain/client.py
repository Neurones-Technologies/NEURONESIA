from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ContractStatus(str, Enum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    RENEWED = "renewed"


class InvoiceStatus(str, Enum):
    PAID = "paid"
    PENDING = "pending"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


@dataclass
class Client:
    client_id: str
    name: str
    sector: Optional[str] = None
    solvency_score: Optional[float] = None
    odoo_id: Optional[int] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


@dataclass
class Contract:
    contract_id: str
    client_id: str
    title: str
    value: float
    currency: str
    start_date: datetime
    end_date: datetime
    status: ContractStatus
    odoo_id: Optional[int] = None

    @property
    def days_until_expiry(self) -> int:
        delta = self.end_date - datetime.now()
        return delta.days


@dataclass
class Invoice:
    invoice_id: str
    client_id: str
    amount: float
    currency: str
    due_date: datetime
    status: InvoiceStatus
    odoo_id: Optional[int] = None
    invoice_date: Optional[datetime] = None
    invoice_name: Optional[str] = None
    payment_date: Optional[datetime] = None
    amount_residual: float = 0.0


@dataclass
class Project:
    project_id: str
    client_id: str
    title: str
    description: str
    start_date: datetime
    end_date: Optional[datetime]
    technologies: list[str] = field(default_factory=list)
    engineers: list[str] = field(default_factory=list)
    odoo_id: Optional[int] = None
