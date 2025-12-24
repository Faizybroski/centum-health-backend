from common.security import verify_password
from common.jwt_utils import create_access_token
from common.config import logger
from datetime import timedelta
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from services.user_service import (
    create_user, get_user_by_email, activate_user, set_reset_token, reset_password
)
from common.email_utils import send_email
from common.utils import normalize_email
from common.config import settings
from fastapi import BackgroundTasks
from common.email_renderer import render_email_template
from common.security import generate_reset_token
from datetime import datetime, timezone


# Existing functions
async def authenticate_user(db, email: str, password: str):
    user = await db["users"].find_one({"email": email})
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    if not user.get("is_active"):
        return None
    # Convert ObjectId to string before returning
    if user and '_id' in user:
        user['_id'] = str(user['_id'])
    return user


def generate_jwt(user: dict):
    token_data = {"sub": user["email"], "user_id": user["_id"]}
    return create_access_token(token_data, expires_delta=timedelta(hours=settings.JWT_EXPIRE_HOURS))


# New route service functions
async def register_user_service(user, background_tasks: BackgroundTasks, db):
    existing = await get_user_by_email(db, user.email)
    if existing:
        return JSONResponse(content={"message": "Email already registered"}, status_code=status.HTTP_400_BAD_REQUEST)
    
    expiry_time = datetime.now(timezone.utc) + timedelta(days=settings.VERIFICATION_TOKEN_EXPIRY_DAYS)
    verification_token, hashed_token = generate_reset_token()
    await create_user(db, user, hashed_token, expiry_time)
   
    verify_url = f"{settings.BACKEND_BASE_URL}/api/v1/auth/verify?token={verification_token}"
    # html = f"<p>Click <a href='{verify_url}'>here</a> to verify your email address.</p>"
    # Render HTML template
    html = render_email_template("verify_email.html", {
        "verification_link": verify_url, 
        "url": settings.BACKEND_BASE_URL,
        "user_name": (user.full_name).title()
    })

    # Welcome email
    onboarding_url = f"{settings.FRONTEND_BASE_URL}/customer/health-assessment"
    upload_url = f"{settings.FRONTEND_BASE_URL}/customer/upload-new-report"
    welcome_html = render_email_template("welcome_email_template.html", {
        "onboarding_link": onboarding_url,
        "upload_link": upload_url,
        "support_email": settings.ADMIN_EMAIL,
        "current_year": datetime.now().year,
        "url": settings.BACKEND_BASE_URL,
        "user_name": (user.full_name).title()
    })
    background_tasks.add_task(send_email, user.email, "Verify your email", html)
    background_tasks.add_task(send_email, user.email, "Welcome to Centum Health Tracker!", welcome_html)
    return JSONResponse(content={"message": "Registration successful. Check your email to verify your account."}, status_code=status.HTTP_200_OK)


async def verify_email_service(token, db):
    if not await activate_user(db, token):
        return False #Invalid or expired verification link
    return True #Email verified. You can now log in


async def login_user_service(login_data, db):
    try: 
        email = normalize_email(login_data.email)
        user = await db["users"].find_one({"email": email})
        if not user:
            return JSONResponse(content={"message": "This email address is not registered. Please check for typos or create a new account."}, status_code=status.HTTP_404_NOT_FOUND)
        if not verify_password(login_data.password, user["hashed_password"]):
            return JSONResponse(content={"message": "Invalid credentials."}, status_code=status.HTTP_400_BAD_REQUEST)
        if not user.get("is_active") or not user.get("is_verified"):
            return JSONResponse(content={"message": "Account not verified. Please verify your email."}, status_code=status.HTTP_403_FORBIDDEN)
        if user and '_id' in user:
            user['_id'] = str(user['_id'])
        jwt_token = generate_jwt(user)
        return JSONResponse(content={"access_token": jwt_token, "token_type": "bearer", "role": user.get("role", "customer")}, status_code=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error logging user: {e}")

        return JSONResponse(
            content={"message": "Failed to logging user due to server error."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


async def forgot_password_service(email, background_tasks: BackgroundTasks, db):
    email = normalize_email(email)
    user = await get_user_by_email(db, email)
    
    if not user:
        return JSONResponse(content={"message": "This email address is not registered. Please check for typos or create a new account."}, status_code=status.HTTP_404_NOT_FOUND)

    if not user.get("is_verified"):
        return JSONResponse(content={"message": "Account not verified. Please verify your email."}, status_code=status.HTTP_403_FORBIDDEN)
    
    # reset_token = str(uuid4())
    token, hashed_token = generate_reset_token()

    success, message = await set_reset_token(db, email, hashed_token)

    if not success:
        return JSONResponse(content={"message": message}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    reset_url = f"{settings.FRONTEND_BASE_URL}/auth/reset-password?token={token}"
    html = render_email_template("forgot_password.html", {
        "reset_url": reset_url,
        "base_url": settings.BACKEND_BASE_URL
    })
    # html = f"<p>Click <a href='{reset_url}'>here</a> to reset your password.</p>"
    background_tasks.add_task(send_email, email, "Password Reset Request", html)

    return JSONResponse(content={"message": "Password reset link sent to your email."}, status_code=status.HTTP_200_OK)


async def reset_password_service(reset_token, new_password, db):
    if not await reset_password(db, reset_token, new_password):
        return JSONResponse(content={"message": "Invalid or expired reset link."}, status_code=status.HTTP_400_BAD_REQUEST)
    return JSONResponse(content={"message": "Password reset successful. You can now log in."}, status_code=status.HTTP_200_OK)



