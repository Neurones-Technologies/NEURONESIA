from fastapi import APIRouter
from modules.uc10_presales.router import router as uc10_router

router = APIRouter()
router.include_router(uc10_router)
