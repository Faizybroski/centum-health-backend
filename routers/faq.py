from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional

from common.db import get_db
from services.faq_service import get_all_faqs

router = APIRouter(
    prefix="/faq",
    tags=["FAQs"]
)


@router.get("/")
async def read_all_faqs(
    # category: Optional[str] = Query(None, description="Filter FAQs by category"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # return await get_all_faqs(db, category)
    return await get_all_faqs(db)
    
