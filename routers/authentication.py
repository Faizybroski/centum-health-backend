from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import RedirectResponse

from models.user import UserCreate, UserLogin, ResetPassword, ForgotPassword
from models.token import Token
from services.auth_service import (
    register_user_service,
    verify_email_service,
    login_user_service,
    forgot_password_service,
    reset_password_service,
)
from common.db import get_db
from common.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", status_code=201)
async def register(user: UserCreate, background_tasks: BackgroundTasks, db=Depends(get_db)):
    return await register_user_service(user, background_tasks, db)


@router.get("/verify")
async def verify_email(token: str, db=Depends(get_db)):
    try:
        response = await verify_email_service(token, db)
        if response:
            # Redirect to frontend success page
            return RedirectResponse(
                url=f"{settings.FRONTEND_BASE_URL}/auth/verify-email/successfull",
                status_code=302
            )
        else:
            # Redirect to frontend failure page
            return RedirectResponse(
                url=f"{settings.FRONTEND_BASE_URL}/auth/verify-email/failed",
                status_code=302
            )
    except HTTPException as e:
        # Optionally, redirect to a failure page or return JSON
        return RedirectResponse(
            url=f"{settings.FRONTEND_BASE_URL}/auth/verify-email/failed",
            status_code=302
        )


@router.post("/login", response_model=Token)
async def login(login_data: UserLogin, db=Depends(get_db)):
    return await login_user_service(login_data, db)


@router.post("/forgot-password")
async def forgot_password(forgot_password: ForgotPassword, background_tasks: BackgroundTasks, db=Depends(get_db)):
    return await forgot_password_service(forgot_password.email, background_tasks, db)


@router.post("/reset-password")
async def reset_password_endpoint(reset_password: ResetPassword, db=Depends(get_db)):
    return await reset_password_service(reset_password.token, reset_password.new_password, db)
