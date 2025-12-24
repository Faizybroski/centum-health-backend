from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional, List
from bson import ObjectId


async def get_all_faqs(
    db: AsyncIOMotorDatabase,
    category: Optional[str] = None
):
    query = {"is_active": True}

    if category:
        query["category"] = category

    cursor = db.faqs.find(query).sort("created_at", -1)

    faqs = []
    async for faq in cursor:
        faq["_id"] = str(faq["_id"])
        faqs.append(faq)

    return {
        "count": len(faqs),
        "data": faqs
    }
