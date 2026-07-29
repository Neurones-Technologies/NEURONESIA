from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from api.v1.dependencies import CurrentUser
from db.database import AsyncSessionLocal
from db.models import (
    BacklogSnapshotModel,
    ClientModel,
    DossierModel,
    InvoiceModel,
    OpportunityModel,
    PipelineSnapshotModel,
    PurchaseOrderModel,
    SaleOrderModel,
    SupplierInvoiceModel,
    SupplierModel,
)

router = APIRouter(prefix="/stats", tags=["stats"])


class DashboardStats(BaseModel):
    clients: int
    invoices_total: int
    invoices_paid: int
    sale_orders: int
    opportunities: int


@router.get("", response_model=DashboardStats)
async def get_stats(request: Request):
    try:
        odoo = request.app.state.container.odoo_adapter
        stats = await odoo.get_stats()
        return DashboardStats(**stats)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Odoo indisponible: {str(e)}")


# Tables du miroir dont la fraîcheur se lit sur une colonne `synced_at` simple —
# un compte à zéro est un fait réel (jamais synchronisé), pas une erreur.
_MIRROR_TABLES: list[tuple[str, type]] = [
    ("clients", ClientModel),
    ("invoices", InvoiceModel),
    ("sale_orders", SaleOrderModel),
    ("purchase_orders", PurchaseOrderModel),
    ("suppliers", SupplierModel),
    ("supplier_invoices", SupplierInvoiceModel),
    ("opportunities", OpportunityModel),
    ("dossiers", DossierModel),
]

# Journaux d'instantanés (append-only) : la fraîcheur pertinente n'est pas la
# dernière écriture mais la PROFONDEUR d'historique couverte (cf. modèles —
# alimentent M5 et M3, inutilisables tant que l'historique est trop court).
_SNAPSHOT_TABLES: list[tuple[str, type]] = [
    ("pipeline_snapshots", PipelineSnapshotModel),
    ("backlog_snapshots", BacklogSnapshotModel),
]


@router.get("/mirror")
async def mirror_coverage(current_user: CurrentUser):
    """Ce que le miroir Odoo contient réellement : effectif et fraîcheur par
    table, plus la profondeur d'historique des deux journaux d'instantanés.

    Réservé à l'administrateur : une lecture d'infrastructure sur le miroir,
    pas un module métier — même contrôle que le rail frontend, appliqué ici
    côté serveur pour ne pas dépendre du seul masquage d'écran.

    Aucune vue n'est fabriquée ici — une table jamais synchronisée (ex.
    `suppliers`) remonte avec `count: 0` et `last_synced_at: null`, exactement
    ce qui se trouve en base."""
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs")

    async with AsyncSessionLocal() as session:
        tables: dict[str, dict] = {}

        for name, model in _MIRROR_TABLES:
            count, last_synced = (
                await session.execute(select(func.count(), func.max(model.synced_at)).select_from(model))
            ).one()
            tables[name] = {
                "count": count,
                "last_synced_at": last_synced.isoformat() if last_synced else None,
            }

        for name, model in _SNAPSHOT_TABLES:
            count, first_date, last_date = (
                await session.execute(
                    select(func.count(), func.min(model.snapshot_date), func.max(model.snapshot_date))
                )
            ).one()
            tables[name] = {
                "count": count,
                "first_date": first_date.isoformat() if first_date else None,
                "last_date": last_date.isoformat() if last_date else None,
            }

    return {"generated_at": datetime.utcnow().isoformat(), "tables": tables}
