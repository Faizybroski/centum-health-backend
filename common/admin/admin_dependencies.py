from fastapi import Depends, HTTPException, status
from common.jwt_auth import get_current_user
from services.user_service import get_user_by_id
from common.db import get_db
from motor.motor_asyncio import AsyncIOMotorDatabase


async def get_current_admin_user(user_id = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user = await get_user_by_id(user_id, db)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this resource."
        )
    return user_id