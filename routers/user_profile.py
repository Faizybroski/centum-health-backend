from fastapi import APIRouter, Depends, Request
from common.db import get_db
from motor.motor_asyncio import AsyncIOMotorDatabase
from models.user import UserUpdate
from common.jwt_auth import JWTBearer
from services.user_service import get_profile_details, update_user_profile


router = APIRouter(prefix="/user", tags=["User Profile"])



@router.get("/profile")
async def get_profile(user_id: str = Depends(JWTBearer()), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await get_profile_details(user_id, db)


@router.put("/profile")
async def update_profile(user: UserUpdate, user_id: str = Depends(JWTBearer()), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await update_user_profile(user, db, user_id)
