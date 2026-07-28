from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

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
