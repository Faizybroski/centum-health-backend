from datetime import datetime, timezone
from fastapi import status
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from models.contact import SubscribeSchema, ContactUsSchema, WaitlistSchema
from common.email_utils import custom_send_email
from common.utils import normalize_email
from common.config import settings
from fastapi import Depends, BackgroundTasks, Request
from common.db import get_db
from common.email_renderer import render_email_template
from common.config import logger


async def subscribe_user(request: Request, payload: SubscribeSchema, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        html = render_email_template("newsletter_sub_email_to_admin.html", {
            "subscriber_email": payload.email,
            "subscribed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "year": datetime.now().year,
            "app_name": "Centum Health"
        })
        background_tasks.add_task(custom_send_email, settings.EMAIL_FROM, settings.ADMIN_EMAIL, "Centum Health - New Subscriber", html, bcc=settings.SUPPORT_EMAIL, reply_to=payload.email)

        existing = await db.newsletter_subscriptions.find_one({"email": normalize_email(payload.email)})
        if existing:
            if existing.get("status") == "subscribed":
                return JSONResponse(content={"message": "Email already subscribed"}, status_code=status.HTTP_200_OK)
            else:
                # reactivate subscription
                await db.newsletter_subscriptions.update_one(
                    {"email": normalize_email(payload.email)},
                    {"$set": {"status": "subscribed", "updated_at": datetime.now(timezone.utc)}}
                )
                return JSONResponse(content={"message": "Subscribed successfully!"}, status_code=status.HTTP_200_OK)

        await db.newsletter_subscriptions.insert_one({
            "email": normalize_email(payload.email),
            "status": "subscribed",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        return JSONResponse(content={"message": "Subscribed successfully!"}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error subscribing user: {e}")
        return JSONResponse(content={"message": "Failed to subscribe user."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Unsubscribe user
async def unsubscribe_user(payload: SubscribeSchema, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        existing = await db.newsletter_subscriptions.find_one({"email": normalize_email(payload.email)})
        if not existing or existing.get("status") == "unsubscribed":
            return JSONResponse(content={"message": "Email not found or already unsubscribed"}, status_code=status.HTTP_404_NOT_FOUND)

        await db.newsletter_subscriptions.update_one(
            {"email": normalize_email(payload.email)},
            {"$set": {"status": "unsubscribed", "updated_at": datetime.now(timezone.utc)}}
        )
        return JSONResponse(content={"message": "Unsubscribed successfully!"}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error unsubscribing user: {e}")
        return JSONResponse(content={"message": "Failed to unsubscribe user."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Contact us
async def contact_us(request: Request, payload: ContactUsSchema, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        html = render_email_template("contact_us.html", {
            "name": payload.name,
            "email": payload.email,
            "phone": payload.phone,
            "subject": payload.subject,
            "message": payload.message,
            "year": datetime.now().year,
            "app_name": "Centum Health"
        })

        await db.contact_us.insert_one({
            "name": payload.name,
            "email": payload.email,
            "phone": payload.phone,
            "subject": payload.subject,
            "message": payload.message,
            "created_at": datetime.now(timezone.utc)
        })
        background_tasks.add_task(custom_send_email, settings.EMAIL_FROM, settings.ADMIN_EMAIL, "Centum Health - New Contact Us", html, bcc=settings.SUPPORT_EMAIL, reply_to=payload.email)

        return JSONResponse(content={"message": "Your message has been sent successfully! We will get back to you soon."}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error sending contact us email: {e}")
        return JSONResponse(content={"message": "Failed to send contact us email."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Subscription waitlist 
async def subscribe_waitlist(request: Request, payload: WaitlistSchema, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        now = datetime.now(timezone.utc)
        html = render_email_template("waitlist_email_to_admin.html", {
            "subscriber_email": payload.email,
            "subscription_type": (payload.subscription_type).value,
            "subscribed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "year": now.year,
            "app_name": "Centum Health"
        })

        background_tasks.add_task(custom_send_email, settings.EMAIL_FROM, settings.ADMIN_EMAIL, "Centum Health - New Waitlist", html, bcc=settings.SUPPORT_EMAIL, reply_to=payload.email)

        await db.waitlist.update_one(
            {"email": normalize_email(payload.email)},
            {
                "$set": {
                    "subscription_type": payload.subscription_type,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "email": normalize_email(payload.email),
                    "created_at": now
                }
            },
            upsert=True
        )
        return JSONResponse(content={"message": f"Successfully joined the {payload.subscription_type.value} waitlist! We'll notify you when this plan becomes available"}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error adding to waitlist: {e}")
        return JSONResponse(content={"message": "Failed to add to waitlist."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        