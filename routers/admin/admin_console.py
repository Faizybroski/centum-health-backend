from fastapi import APIRouter, Depends, Query, BackgroundTasks
from motor.motor_asyncio import AsyncIOMotorDatabase
from common.db import get_db
from services.admin.admin_console_service import admin_dashboard_console, get_all_users, get_list_of_user_reports, get_failed_reports_with_user_details, retry_user_report_generation
from common.admin.admin_dependencies import get_current_admin_user

router = APIRouter(prefix="/admin", tags=["Admin Console"], dependencies=[Depends(get_current_admin_user)])



@router.get("/dashboard")
async def admin_dashboard(db: AsyncIOMotorDatabase = Depends(get_db)):
    return await admin_dashboard_console(db)


@router.get("/users")
async def all_users(db: AsyncIOMotorDatabase = Depends(get_db), page: int = Query(1, ge=1), limit: int = Query(10, ge=1, le=50), search_value: str = None):
    return await get_all_users(db, page, limit, search_value)


@router.get("/user-reports/{user_id}")
async def user_reports(user_id: str, db: AsyncIOMotorDatabase = Depends(get_db), page: int = Query(1, ge=1), limit: int = Query(10, ge=1, le=50), search_value: str = None):
    return await get_list_of_user_reports(db, user_id, page, limit, search_value)


@router.get("/failed-reports")
async def failed_reports_with_user_details(db: AsyncIOMotorDatabase = Depends(get_db), page: int = Query(1, ge=1), limit: int = Query(10, ge=1, le=50), search_value: str = None):
    return await get_failed_reports_with_user_details(db, page, limit, search_value)


@router.post("/retry-report-generation/{report_id}")
async def retry_report_generation(report_id: str, background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await retry_user_report_generation(db, report_id, background_tasks)

