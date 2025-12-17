from fastapi import APIRouter, Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from common.db import get_db
from models.contact import SubscribeSchema, ContactUsSchema, WaitlistSchema
from services.contact_service import subscribe_user, unsubscribe_user, contact_us, subscribe_waitlist
from fastapi import BackgroundTasks
from common.rate_limiter import limiter


router = APIRouter(prefix="/contact", tags=["Contact & Subscription"])


# Subscribe newsletter 
@router.post("/subscribe")
@limiter.limit("3/hour")
async def subscribe(request: Request, payload: SubscribeSchema, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await subscribe_user(request, payload, background_tasks, db)


# Unsubscribe
# @router.post("/unsubscribe")
# async def unsubscribe(payload: SubscribeSchema, db: AsyncIOMotorDatabase = Depends(get_db)):
#     return await unsubscribe_user(payload, db)


# Contact Us API
@router.post("/contact-us")
@limiter.limit("3/hour")
async def contact(request: Request, payload: ContactUsSchema, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await contact_us(request, payload, background_tasks, db)


# Waitlist subscription 
@router.post("/join-waitlist")
@limiter.limit("5/hour")
async def join_waitlist(request: Request, payload: WaitlistSchema, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await subscribe_waitlist(request, payload, background_tasks, db)
