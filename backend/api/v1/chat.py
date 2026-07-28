from fastapi import APIRouter
from modules.uc02_capital_knowledge.router import router as uc02_router

router = APIRouter()
router.include_router(uc02_router)
