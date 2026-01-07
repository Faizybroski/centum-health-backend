from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi.responses import JSONResponse
from fastapi import status, HTTPException
from models.faqs import FAQStatus
from typing import Optional, List
from common.config import logger
from bson import ObjectId


# async def get_all_faqs(db: AsyncIOMotorDatabase, category: Optional[str] = None):
async def get_all_faqs(db: AsyncIOMotorDatabase):

    try: 
        query = {"status": FAQStatus.saved}

        # if category:
        #     query["category"] = category

        cursor = db.faqs.find(query).sort("_id", 1)

        faqs = []
        async for faq in cursor:
            faq["_id"] = str(faq["_id"])
            faqs.append(faq)

        return JSONResponse(content={"message": "FAQ fetched successfully", "count": len(faqs), "data": faqs}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching faqs: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch faqs."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
