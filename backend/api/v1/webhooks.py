"""
Webhook Odoo → FastAPI

Configuration côté Odoo (Paramètres → Technique → Actions automatisées) :
  - Modèle : sale.order (ou account.move, res.partner, purchase.order)
  - Déclencheur : À la création / À la mise à jour
  - Action : Appel d'URL
  - URL : https://ton-serveur.com/v1/webhooks/odoo
  - Méthode : POST
  - Corps :
    {
      "secret": "TON_SECRET",
      "model": "{{ object._name }}",
      "ids": [{{ object.id }}],
      "action": "write"
    }

En développement local, utiliser ngrok :
  ngrok http 8000
  → copier l'URL HTTPS dans les actions Odoo
"""
import hmac
import logging

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel

from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

_SUPPORTED_MODELS = {"sale.order", "account.move", "res.partner", "purchase.order"}


class OdooWebhookPayload(BaseModel):
    model: str
    ids: list[int]
    action: str = "write"   # create | write | unlink
    secret: str = ""


@router.post("/odoo")
async def odoo_webhook(payload: OdooWebhookPayload, background_tasks: BackgroundTasks):
    """
    Reçoit les événements Odoo et met à jour le miroir SQLite en arrière-plan.
    Configurer dans Odoo : Actions automatisées → Appel d'URL.
    """
    # Vérification du secret (si configuré)
    if settings.odoo_webhook_secret:
        if not hmac.compare_digest(payload.secret, settings.odoo_webhook_secret):
            logger.warning("Webhook rejeté : secret invalide")
            raise HTTPException(status_code=401, detail="Secret invalide")

    if payload.model not in _SUPPORTED_MODELS:
        logger.info("Webhook ignoré : modèle non géré (%s)", payload.model)
        return {"status": "ignored", "reason": f"Modèle non géré : {payload.model}"}

    if not payload.ids:
        return {"status": "ignored", "reason": "Aucun ID fourni"}

    logger.info("Webhook reçu : %s %s ids=%s", payload.action, payload.model, payload.ids[:5])

    # Sync en arrière-plan pour ne pas bloquer la réponse
    background_tasks.add_task(_handle_webhook, payload.model, payload.ids, payload.action)

    return {"status": "accepted", "model": payload.model, "ids_count": len(payload.ids)}


async def _handle_webhook(model: str, ids: list[int], action: str):
    try:
        if action == "unlink":
            await _handle_delete(model, ids)
        else:
            from jobs.odoo_sync_job import sync_records_by_id
            await sync_records_by_id(model, ids)
    except Exception as e:
        logger.error("Erreur traitement webhook %s %s : %s", model, ids, e, exc_info=True)


async def _handle_delete(model: str, ids: list[int]):
    from db.database import AsyncSessionLocal
    from db.models import SaleOrderModel, InvoiceModel, ClientModel, PurchaseOrderModel

    model_map = {
        "sale.order": (SaleOrderModel, lambda i: f"so_{i}"),
        "account.move": (InvoiceModel, lambda i: str(i)),
        "res.partner": (ClientModel, lambda i: str(i)),
        "purchase.order": (PurchaseOrderModel, lambda i: f"po_{i}"),
    }
    if model not in model_map:
        return

    ModelClass, id_fn = model_map[model]
    async with AsyncSessionLocal() as session:
        for odoo_id in ids:
            obj = await session.get(ModelClass, id_fn(odoo_id))
            if obj:
                await session.delete(obj)
        await session.commit()
    logger.info("Webhook unlink : %d enregistrements supprimés (%s)", len(ids), model)


@router.post("/odoo/force-sync")
async def force_full_sync(background_tasks: BackgroundTasks, request: Request):
    """Déclenche une synchronisation complète immédiate (admin uniquement)."""
    background_tasks.add_task(_run_full_sync)
    return {"status": "started", "message": "Synchronisation complète déclenchée en arrière-plan"}


async def _run_full_sync():
    try:
        from jobs.odoo_sync_job import run_odoo_sync
        result = await run_odoo_sync(force_full=True)
        logger.info("Force sync terminée : %s", result)
    except Exception as e:
        logger.error("Erreur force sync : %s", e, exc_info=True)
