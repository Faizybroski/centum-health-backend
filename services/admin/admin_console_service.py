from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import status, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from common.config import logger
from typing import List, Optional
from bson import ObjectId
from fastapi import BackgroundTasks
from services.health_assessment_service import generate_and_upsert_clinical_summary
# from models.faqs import FAQCreate, FAQInDB, FAQUpdate, FAQStatus
from models.faqs import FAQCreate, FAQUpdate, FAQStatus
from datetime import datetime, timezone
from bson.regex import Regex
from math import ceil

# Get the list of all active users
async def get_all_users(db: AsyncIOMotorDatabase, page: int ,limit: int ,search_value: str):
    try:
        match_query = {"role": "customer"}
        if search_value:
            match_query["full_name"] = {"$regex": search_value, "$options": "i"}

        skip_count = (page - 1) * limit

        pipeline = [
            {"$match": match_query},
            {"$skip": skip_count},
            {"$limit": limit},
            {"$project": {
                "_id": 0,                        # Exclude original _id field
                "id": {"$toString": "$_id"},     # Include id as string
                "email": 1,
                "full_name": 1,
                "gender": 1,
                "phone_number": 1,
                "date_of_birth": 1,
                "is_active": 1
            }}
        ]
        all_users = await db.users.aggregate(pipeline)
        total_users = await db.users.count_documents(match_query)

        return JSONResponse(
            content={
                "data": {
                    "list": all_users,
                    "total_count": total_users,
                    "current_page": page,
                    "limit": limit,
                    "total_pages": total_users // limit + (total_users % limit > 0) if total_users > 0 else 1
                },
                "message": "Users fetched successfully" if all_users else "No users found"
            },
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch users."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Get the list of reports with user details and documents
async def get_list_of_user_reports(db: AsyncIOMotorDatabase, user_id: str, page: int, limit: int, search_value: str):
    try:
        skip = (page - 1) * limit

        # Base filter
        match_filter = {"user_id": ObjectId(user_id)}
        if search_value:
            match_filter["report_title"] = {"$regex": Regex(search_value, "i")}

        # ---- Count total documents ----
        total_count = await db.user_reports.count_documents(match_filter)
        total_pages = ceil(total_count / limit) if total_count > 0 else 1

        # ---- Main pipeline ----
        pipeline = [
            {"$match": match_filter},
            {"$sort": {"updated_at": -1}},
            {
                "$lookup": {
                    "from": "documents",
                    "localField": "document_ids",
                    "foreignField": "_id",
                    "as": "documents_info"
                },
            },
            {
                "$project": {
                    "_id": 0,
                    "report_title": 1,
                    "status": 1,
                    "health_score": {"$ifNull": ["$health_score", 0]},
                    "updated_at": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$updated_at"
                        }
                    },
                    "uploaded_documents": {
                        "$map": {
                            "input": "$documents_info",
                            "as": "doc",
                            "in": {
                                "file_name": "$$doc.file_name",
                                "file_path": "$$doc.path"
                            }
                        }
                    },
                }
            },
            {"$skip": skip},
            {"$limit": limit},
        ]

        reports = await db.user_reports.aggregate(pipeline)

        # ---- Fetch user details ----
        user = await db.users.find_one(
            {"_id": ObjectId(user_id), "role": "customer"},
            {
                "_id": 0,
                "full_name": 1,
                "email": 1,
                "gender": 1,
                "phone_number": 1,
                "date_of_birth": 1,
                "is_active": 1,
                "created_at": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$created_at"
                    }
                },
                "updated_at": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$updated_at"
                    }
                }
            }
        )

        data = {
            "user": user or {},
            "list": reports or [],
            "total_count": total_count,
            "current_page": page,
            "limit": limit,
            "total_pages": total_pages,
        }

        return JSONResponse(
            content={
                "data": data,
                "message": "Reports fetched successfully." if reports else "No reports found."
            },
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error fetching reports: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch reports."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Get the list of failed reports with user details
async def get_failed_reports_with_user_details(db: AsyncIOMotorDatabase, page: int ,limit: int ,search_value: str):
    try:
        skip = (page - 1) * limit

        # Aggregation pipeline
        search_filter = []
        if search_value:
            search_filter.append({
                "$match": {
                    "$or": [
                        {"user.full_name": {"$regex": Regex(search_value, "i")}},
                        {"user.email": {"$regex": Regex(search_value, "i")}},
                        {"report_title": {"$regex": Regex(search_value, "i")}},
                    ]
                }
            })

        pipeline = [
            {"$match": {"status": "failed"}},
            {
                "$lookup": {
                    "from": "users",
                    "localField": "user_id",
                    "foreignField": "_id",
                    "as": "user"
                }
            },
            {"$unwind": "$user"},
            *search_filter,
            {
                "$facet": {
                    "data": [
                        {"$sort": {"updated_at": -1}},
                        {"$skip": skip},
                        {"$limit": limit},
                        {"$project": {
                            "_id": 0,
                            "id": {"$toString": "$_id"},
                            "report_title": 1,
                            "status": 1,
                            "updated_at": {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$updated_at"
                                }
                            },
                            "user_name": "$user.full_name",
                            "email": "$user.email",
                            "gender": "$user.gender",
                            "phone_number": "$user.phone_number",
                            "date_of_birth": "$user.date_of_birth",
                            "is_active": "$user.is_active"
                        }}
                    ],
                    "total_count": [
                        {"$count": "count"}
                    ]
                }
            }
        ]

        result = await db.user_reports.aggregate(pipeline)

        reports = result[0]["data"] if result else []
        total_count = result[0]["total_count"][0]["count"] if result and result[0]["total_count"] else 0
        total_pages = ceil(total_count / limit)

        data = {
            "list": reports or [],
            "total_count": total_count,
            "current_page": page,
            "limit": limit,
            "total_pages": total_pages,
        }
        return JSONResponse(
            content={"data": data, 
            "message": "Failed reports fetched successfully." if reports else "No failed reports found."},
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Error fetching failed reports: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch reports."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Retry report generation
async def retry_user_report_generation(db: AsyncIOMotorDatabase, report_id: str, background_tasks: BackgroundTasks):
    try:
        logger.info("Retry report generation called for report id: %s", report_id)
        report = await db.user_reports.find_one({"_id": ObjectId(report_id)})
        if not report:
            logger.info("Report not found.")
            return JSONResponse(content={"message": "Report not found."}, status_code=status.HTTP_404_NOT_FOUND)
        
        if report["status"] != "failed":
            logger.info("Report is not in failed state.")
            return JSONResponse(content={"message": "Report is not in failed state."}, status_code=status.HTTP_400_BAD_REQUEST)
        
        # Get current retry count or initialize to 0
        retry_count = report.get("retry_count", 0)
        
        # Check if max retries reached
        if retry_count >= 3:
            logger.info("Maximum retry attempts (3) reached. Please contact support for further assistance.")
            return JSONResponse(
                content={"message": "Maximum retry attempts (3) reached. Please contact support for further assistance."},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Increment retry count and update status to pending
        await db.user_reports.update_one(
            {"_id": ObjectId(report_id)},
            {
                "$set": {
                    "status": "pending",
                    "retry_count": retry_count + 1,
                    "error": "",
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        # Retry report generation
        background_tasks.add_task(generate_and_upsert_clinical_summary, db, report["user_id"], report["document_ids"], report_id)
        
        return JSONResponse(
            content={"message": f"Report generation retry initiated. Attempt {retry_count + 1} of 3."},
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Error retrying report generation: {e}")
        return JSONResponse(
            content={"message": "Failed to retry report generation."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Admin dashboard
async def admin_dashboard_console(db: AsyncIOMotorDatabase):
    try:
        # Get total number of users
        total_users = await db.users.count_documents({"role": "customer"})
        
        # Get total number of active users
        active_users = await db.users.count_documents({"is_active": True, "role": "customer"})
        
        # Get total number of failed reports
        failed_reports = await db.user_reports.count_documents({"status": "failed"})
        
        # Get total number of pending reports
        total_reports = await db.user_reports.count_documents({})
        
        cursor = await db.users.find({"role": "customer"}, {"_id": 0, "full_name": 1, "email": 1, "gender": 1, "phone_number": 1, "date_of_birth": 1, "is_active": 1})
        users = sorted(cursor, key=lambda x: x.get("created_at", ""), reverse=True)
        last_20_users = users[:20]
        # cursor = db.users.find({"role": "customer"}, {"_id": 0, "full_name": 1, "email": 1, "gender": 1, "phone_number": 1, "date_of_birth": 1, "is_active": 1}).sort([("created_at", -1)]).limit(20)
        # last_20_users = await cursor.to_list(length=20)
        data = {
            "total_users": total_users,
            "active_users": active_users,
            "failed_reports": failed_reports,
            "total_reports": total_reports,
            "users": last_20_users
        }
        return JSONResponse(
            content={"data": data, "message": "Admin dashboard data fetched successfully."},
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Error fetching admin dashboard data: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch admin dashboard data."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
# async def get_all_faqs(db: AsyncIOMotorDatabase, category: Optional[str] = None):
async def get_all_faqs(db: AsyncIOMotorDatabase):
    try: 

        query = {}

        # if category:
        #     query["category"] = category

        cursor = db.faqs.find(query).sort("created_at", -1)

        faqs = []
        async for faq in cursor:
            faq["_id"] = str(faq["_id"])
            faqs.append(faq)

        return JSONResponse(
            content=jsonable_encoder({ 
                "message": "FAQ fetched successfully",
                "count": len(faqs),
                "data": faqs
            }),
            status_code=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        logger.error(f"Error fetching faqs: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch faqs."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

async def create_general_faq(payload: FAQCreate, db: AsyncIOMotorDatabase):
    try:
        # # faq = FAQInDB(
        # # **payload.dict(),
        # # created_at=datetime.utcnow(),
        # # updated_at=datetime.utcnow(),
        # # is_active=True
        # # )

        # # result = await db.faqs.insert_one(faq.dict(by_alias=True))
        # faq = payload.model_dump()
        # faq.setdefault("status", FAQStatus.draft)
        # faq["created_at"] = datetime.utcnow()
        # faq["updated_at"] = datetime.utcnow()
        
        # # if existing_faq.status == "saved" and payload.status == "draft": 
        #     # payload.status = "saved"

        # result = await db.faqs.insert_one(faq)
        # # return {"message": "FAQ created", "status": faq["status"]}
        
        # return JSONResponse(
        #     content={
        #         "message": "FAQ created successfully",
        #         "faq_id": str(result.inserted_id),
        #          "status": faq["status"]
        #     },
        #     status_code=status.HTTP_201_CREATED
        # )
        faq = {
            **payload.dict(),
            "status": payload.status or "draft",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        result = await db.faqs.insert_one(faq)
        return JSONResponse(
            content={ "message": "FAQ created successfully",
                "faq_id": str(result.inserted_id),
                "status": faq["status"]
            },
            status_code=status.HTTP_201_CREATED
        )


    except Exception as e:
        logger.error(f"Error creating FAQ: {e}")
        return JSONResponse(
            content={"message": "Failed to create FAQ."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

async def update_general_faq(faq_id: str, payload: FAQUpdate, db: AsyncIOMotorDatabase):
    try:
        # # update_data = {k: v for k, v in payload.dict(exclude_unset=True).items()}

        # # if not update_data:
        #     # return JSONResponse(
        #         # content={"message": "No fields provided for update"},
        #         # status_code=status.HTTP_400_BAD_REQUEST
        #     # )

        # # update_data["updated_at"] = datetime.utcnow()
        
        # existing_faq = await db.faqs.find_one(
        #     {"_id": ObjectId(faq_id)}
        # )
        
        # if not existing_faq:
        #     raise HTTPException(status_code=404, detail="FAQ not found")
            
        # update_data = payload.model_dump(exclude_unset=True)
        
        # if (
        #     existing_faq.get("status") == FAQStatus.saved
        #     and update_data.get("status") == FAQStatus.draft
        # ):
        #     update_data["status"] = FAQStatus.saved
        
        # update_data["updated_at"] = datetime.utcnow()

        # result = await db.faqs.update_one(
        #     {"_id": ObjectId(faq_id), "is_active": True},
        #     {"$set": update_data}
        # )

        # if result.matched_count == 0:
        #     return JSONResponse(
        #         content={"message": "FAQ not found or already deleted"},
        #         status_code=status.HTTP_404_NOT_FOUND
        #     )
        
        update = payload.dict(exclude_unset=True)
        update["updated_at"] = datetime.now(timezone.utc)

        result = await db.faqs.update_one(
            {"_id": ObjectId(faq_id)},
            {"$set": update}
        )
        
        if result.matched_count == 0:
            return JSONResponse(
                content={"message": "FAQ not found"},
                status_code=status.HTTP_404_NOT_FOUND
            )

        return JSONResponse(
            content=jsonable_encoder({"message": "FAQ updated successfully", "updated_faq": update}),
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error updating FAQ: {e}")

        return JSONResponse(
            content={"message": "Failed to update FAQ"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
async def publish_general_faq(faq_id: str, db: AsyncIOMotorDatabase):
    try:
        result = await db.faqs.update_one(
            {"_id": ObjectId(faq_id)},
            {
                "$set": {
                    "status": FAQStatus.saved,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        if result.matched_count == 0:
            return JSONResponse(
                content={"message": "FAQ not found"},
                status_code=status.HTTP_404_NOT_FOUND
            )

        return JSONResponse(
            content={"message": "FAQ saved successfully"},
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error saving FAQ: {e}")

        return JSONResponse(
            content={"message": "Failed to save FAQ"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
async def unpublish_general_faq(faq_id: str, db: AsyncIOMotorDatabase):
    try:
        result = await db.faqs.update_one(
            {"_id": ObjectId(faq_id)},
            {
                "$set": {
                    "status": FAQStatus.draft,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        if result.matched_count == 0:
            return JSONResponse(
                content={"message": "FAQ not found"},
                status_code=status.HTTP_404_NOT_FOUND
            )

        return JSONResponse(
            content={"message": "FAQ unpublished successfully"},
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error unpublishing FAQ: {e}")

        return JSONResponse(
            content={"message": "Failed to unpublish FAQ"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

async def delete_general_faq(faq_id: str, db: AsyncIOMotorDatabase):
    try:
        result = await db.faqs.delete_one(
            {"_id": ObjectId(faq_id)}
        )

        if result.deleted_count  == 0:
            return JSONResponse(
                content={"message": "FAQ not found or already deleted"},
                status_code=status.HTTP_404_NOT_FOUND
            )

        return JSONResponse(
            content={"message": "FAQ deleted successfully"},
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error deleting FAQ: {e}")

        return JSONResponse(
            content={"message": "Failed to delete FAQ"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

async def waitlist_data(
    db: AsyncIOMotorDatabase,
    page: int,
    limit: int,
    subscription_type: Optional[str],
    search_value: Optional[str],
):
    try:
        skip = (page - 1) * limit
        query = {}

        if subscription_type:
            query["subscription_type"] = subscription_type

        if search_value:
            query["email"] = {"$regex": search_value, "$options": "i"}

        total_count = await db.waitlist.count_documents(query)
        

        cursor = (
            db.waitlist
            .find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

        # cursor = (
        #     db.waitlist
        #     .find(query)
        #     .skip(skip)
        #     .limit(limit)
        # )

        subscriptions = await cursor.to_list(length=limit)

        # 🔑 FIX: serialize ObjectId
        subscriptions = [
            {**sub, "_id": str(sub["_id"])}
            for sub in subscriptions
        ]
        
        # 🔥 NEW: subscription_type-wise counts (UNFILTERED by pagination)
        pipeline = [
            {"$match": query if query else {}},
            {
                "$group": {
                    "_id": "$subscription_type",
                    "count": {"$sum": 1}
                }
            }
        ]
        
        counts_cursor = db.waitlist.aggregate(pipeline)
        counts_raw = await counts_cursor.to_list(length=None)

        subscription_counts = {
            item["_id"] or "unknown": item["count"]
            for item in counts_raw
        }

        return JSONResponse(
            content=jsonable_encoder({
                "data": {
                    "total_count": total_count,
                    "current_page": page,
                    "limit": limit,
                    "list": subscriptions,
                    "total_pages": (total_count // limit + (total_count % limit > 0) if total_count > 0 else 1),
                    "subscription_counts": subscription_counts,
                },
                "message": "Waitlists fetched successfully" if subscriptions else "No waitlist found"
            }),
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Error fetching waitlist subscriptions: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch waitlist subscriptions."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        
async def get_waitlist_subscription_by_id(db: AsyncIOMotorDatabase, id: str):
    try:
        subscription = await db.waitlist.find_one({"_id": ObjectId(id)})

        if not subscription:
            return JSONResponse(
                content={"message": "Waitlist subscription not found."},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 🔑 FIX: serialize ObjectId
        subscription["_id"] = str(subscription["_id"])

        return JSONResponse(
            content=jsonable_encoder({
                "data": subscription,
                "message": "Waitlist subscription fetched successfully."
            }),
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Error fetching waitlist subscription by id: {e}")
        return JSONResponse(
            content={"message": "Failed to fetch waitlist subscription."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )