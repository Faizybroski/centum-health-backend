from typing import Optional
from bson import ObjectId
from fastapi import HTTPException, status, BackgroundTasks
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import Depends, Request
from models.user import UserCreate, UserInDB, UserUpdate
from common.security import hash_password
from datetime import datetime, timezone, date, timedelta, time
from common.utils import normalize_email
from fastapi.responses import JSONResponse
from data_processing.calculate_age import calculate_chronological_age, calculate_biological_age
from common.config import logger, settings
from common.email_utils import custom_send_email
from common.email_renderer import render_email_template
# from common.security import encrypt_fields, decrypt_fields
# from common.security import Encryptor
import hashlib
# encryptor = Encryptor()
from common.security import _encrypt_value

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_user(db: AsyncIOMotorDatabase, user: UserCreate, verification_token: str, token_expiry_time: datetime) -> Optional[UserInDB]:
    user_dict = user.model_dump()
    # Convert date_of_birth to ISO string if present
    dob = user_dict.get("date_of_birth")
    if isinstance(dob, str):
        try:
            parsed_dob = datetime.strptime(dob, "%m/%d/%Y").date()
            user_dict["date_of_birth"] = parsed_dob.strftime("%m/%d/%Y")
        except ValueError:
            raise ValueError("Invalid date format for date_of_birth. Expected MM/DD/YYYY.")

    user_dict["email"] = normalize_email(user_dict.get("email"))
    user_dict["hashed_password"] = hash_password(user.password)
    user_dict.pop("password")
    user_dict["is_active"] = False
    user_dict["is_verified"] = False
    user_dict["verification_token"] = verification_token
    user_dict["verification_token_expiry_time"] = token_expiry_time
    user_dict["created_at"] = datetime.now(timezone.utc)
    user_dict["updated_at"] = datetime.now(timezone.utc)
    user_dict["role"] = "customer"
    chronological_age = await calculate_chronological_age(dob)
    user_dict["chronological_age"] = chronological_age
    # user = EncryptedCollection(db["users"])

    result = await db["users"].insert_one(user_dict)

    user_in_db_dict = user_dict.copy()
    user_in_db_dict["id"] = result.inserted_id
    
    # Ensure reset_token is present
    if "reset_token" not in user_in_db_dict:
        user_in_db_dict["reset_token"] = None

    return UserInDB(**user_in_db_dict)


async def get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[dict]:
    email = normalize_email(email)
    return await db["users"].find_one({"email": email})


async def get_user_by_id(user_id: str, db: AsyncIOMotorDatabase) -> Optional[dict]:
    return await db["users"].find_one({"_id": ObjectId(user_id)})


async def activate_user(db: AsyncIOMotorDatabase, token: str) -> bool:
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    result = await db["users"].update_one(
        {
            "verification_token": hashed_token,
            "verification_token_expiry_time": {"$gt": now}
        },
        {
            "$set": {"is_active": True, "is_verified": True},
            "$unset": {"verification_token": "", "verification_token_expiry_time": ""}
        }
    )

    if result.modified_count == 1:
        return True
    else:
        return False


# Get profile details
async def get_profile_details(user: str, db: AsyncIOMotorDatabase):
    pipeline = [
        {"$match": {"_id": ObjectId(user)}},
        {"$project": {
            "_id": 1, 
            "full_name": 1, 
            "email": 1, 
            "gender": 1, 
            "phone_number": 1,
            "individual_reference_number": 1,
            "madicare_card_number": 1,
            "madicare_expiry_date": 1,
            "date_of_birth": 1, 
            "role": 1
        }},
        # health assessment lookup
        {"$lookup": {
            "from": "health_assessment_responses",
            "localField": "_id",
            "foreignField": "user_id",
            "as": "health_assessment"
        }},
        {"$addFields": {
            "is_health_assessment_complete": {
                "$ifNull": [
                    {"$arrayElemAt": ["$health_assessment.is_health_assessment_complete", 0]},
                    False
                ]
            }
        }},
        {"$project": {"health_assessment": 0}},

        # newsletter lookup
        {"$lookup": {
            "from": "newsletter_subscriptions",
            "let": {"email": "$email"},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$and": [
                            {"$eq": ["$email", "$$email"]},
                            {"$eq": ["$status", "subscribed"]}
                        ]
                    }
                }}
            ],
            "as": "newsletter"
        }},
        {"$addFields": {
            "is_newsletter_subscribed": {
                "$cond": {
                    "if": {"$gt": [{"$size": "$newsletter"}, 0]},
                    "then": True,
                    "else": False
                }
            }
        }},
        {"$project": {"newsletter": 0}}
    ]

    result = await db["users"].aggregate(pipeline)
    # result = await result.to_list(length=1)
    if not result:
        return JSONResponse(
            content={"error": "User not found"},
            status_code=status.HTTP_404_NOT_FOUND
        )

    user = result[0]
    user['id'] = str(user['_id'])
    user.pop('_id')

    return JSONResponse(content=user, status_code=status.HTTP_200_OK)


# Set reset token
async def set_reset_token(db: AsyncIOMotorDatabase, email: str, token: str) -> tuple[bool, str]:
    email = normalize_email(email)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.RESET_WINDOW_MINUTES)

    user = await db["users"].find_one({"email": email})

    if not user:
        return False, "User not found."

    # Get and filter previous attempts
    request_times = user.get("reset_token_requests", [])
    recent_requests = [t for t in request_times if datetime.fromisoformat(t) > cutoff]

    if len(recent_requests) >= settings.MAX_RESET_ATTEMPTS:
        return False, "Too many reset attempts. Please try again later."

    # Append current attempt
    recent_requests.append(now.isoformat())

    # Update DB with new token and request times
    await db["users"].update_one(
        {"email": email},
        {
            "$set": {
                "reset_token": token,
                "reset_token_created_at": now,
                "reset_token_requests": recent_requests
            }
        }
    )

    return True, "Reset token set."


async def reset_password(db: AsyncIOMotorDatabase, reset_token: str, new_password: str) -> bool:
    try:
        now = datetime.now(timezone.utc)
        token_expiry_time = now - timedelta(minutes=settings.RESET_TOKEN_EXPIRY_MINUTES)

        hashed_token = hashlib.sha256(reset_token.encode()).hexdigest()
        # Find user with matching token that is not expired
        user = await db["users"].find_one({
            "reset_token": hashed_token,
            "reset_token_created_at": {"$gte": token_expiry_time}
        })

        if not user:
            return False  # Token is invalid or expired

        hashed = hash_password(new_password)

        result = await db["users"].update_one(
            {"_id": user["_id"]},
            {
                "$set": {"hashed_password": hashed},
                "$unset": {
                    "reset_token": "",
                    "reset_token_created_at": ""
                }
            }
        )

        return result.modified_count == 1
    except Exception as e:
        logger.error(f"Exception: reset password failed: {e}")
        return False


# update user profile
async def update_user_profile(user: UserUpdate, db: AsyncIOMotorDatabase, user_id: str):
    try:
        chronological_age = await calculate_chronological_age(user.date_of_birth)
        biological_age_object = await calculate_biological_age(db, user_id, chronological_age)
        # encrypted_data = encrypt_fields(user.model_dump(), ["full_name", "phone_number", "date_of_birth", "gender"], encryptor)
        # Convert to datetime for Mongo compatibility
        to_update = user.model_dump()
        
        to_update.update({
            "chronological_age": chronological_age,
            "biological_age": biological_age_object['biological_age'],
            "adjustment_cap": biological_age_object['adjustment_cap'],
            "risk_points": biological_age_object['risk_points'],
            "risk_percent": biological_age_object['risk_percent'],
            "raw_biological_age": biological_age_object['raw_biological_age'],
            "max_negative_cap": biological_age_object['max_negative_cap'],
            "max_positive_cap": biological_age_object['max_positive_cap'],
            "sum_weights": biological_age_object['sum_weights'],
            "s_max": biological_age_object['s_max'],
            "updated_at": datetime.now(timezone.utc)
        })
        await db['users'].update_one(
            {"_id": ObjectId(user_id)},
            {"$set":to_update}
        )
        return JSONResponse(content={"message": "Profile updated successfully."}, status_code=status.HTTP_200_OK)        
    except Exception as e:
        logger.error(f"Exception: profile update failed: {e}")
        return JSONResponse(content={"error": "Failed to update profile."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
async def delete_user_account_service(user_id, db):
    try:
        result = await db.users.delete_one({"_id": ObjectId(user_id)})

        if result.deleted_count == 0:
            return JSONResponse(
                content={"message": "User not found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
            
        return JSONResponse(
            content={"message": "User account permanently deleted", "user": user_id},
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Exception: profile detetion failed: {e}")
        return JSONResponse(content={"error": "Failed to delete profile."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

async def change_password_service(user_id: str, payload, db, background_tasks: BackgroundTasks):
    try: 
        user = await db.users.find_one({"_id": ObjectId(user_id)})

        if not user:
            return JSONResponse(
                {"message": "User not found"},
                status_code=status.HTTP_404_NOT_FOUND
            )

        if not pwd_context.verify(payload.current_password, user["hashed_password"]):
            return JSONResponse(
                {"message": "Current password is incorrect"},
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if payload.new_password != payload.confirm_new_password:
            return JSONResponse(
                {"message": "New passwords do not match"},
                status_code=status.HTTP_400_BAD_REQUEST
            )

        hashed_password = pwd_context.hash(payload.new_password)

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"hashed_password": hashed_password}}
        )
        
        html = render_email_template("changePass.html", {
            "email": user["email"],
            "full_name": user["full_name"],
            "changed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "year": datetime.now().year,
            "app_name": "Centum Health",
        })
        
        background_tasks.add_task(custom_send_email, settings.EMAIL_FROM, user["email"], "Centum Health - Password Changed", html, bcc=settings.SUPPORT_EMAIL, reply_to=settings.EMAIL_FROM)
        

        return JSONResponse(
            {"message": "Password changed successfully"},
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Exception: account password changing failed: {e}")
        return JSONResponse(content={"error": "Failed to change password."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)