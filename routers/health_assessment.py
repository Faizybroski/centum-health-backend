from typing import List
from fastapi import APIRouter, Depends, BackgroundTasks
from motor.motor_asyncio import AsyncIOMotorDatabase

from models.health_assessment import SaveStepRequest, CompareRequest, VO2MaxUpdate
from common.jwt_auth import get_current_user
from common.db import get_db
from services.health_assessment_service import (create_report, save_health_assessment_step,
         get_user_reports, get_user_report_details, get_health_assessment_form_step, dashboard_data, compare_two_reports, update_vo2_max_value)


router = APIRouter(prefix="/health-assessment", tags=["Health Assessment"])


@router.post("/save-step")
async def save_step(req: SaveStepRequest, db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await save_health_assessment_step(db, user_id, req.step_number, req.form_data)


@router.get("/form-step/{step_number}")
async def get_form_step(step_number: int,db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await get_health_assessment_form_step(db, user_id, step_number)


@router.post("/generate-report")
async def generate_report(document_ids: List[str], report_title: str, report_date: str, report_category: str, report_notes: str,
    background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await create_report(db, user_id, report_title, document_ids, background_tasks, report_date, report_category, report_notes)


@router.get("/reports")
async def get_reports(db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await get_user_reports(db, user_id)


@router.get("/report/{report_id}")
async def get_report_details(report_id: str, db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await get_user_report_details(db, user_id, report_id)


@router.get("/dashboard")
async def get_dashboard_data(db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await dashboard_data(db, user_id)


@router.post("/compare-user-reports")
async def compare_user_reports(compare: CompareRequest, db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await compare_two_reports(db, user_id, compare.report_id_1, compare.report_id_2)


@router.patch("/vo2-max")
async def update_vo2_max(vo2_max: VO2MaxUpdate, db: AsyncIOMotorDatabase = Depends(get_db),
    user_id: dict = Depends(get_current_user)):
    return await update_vo2_max_value(db, user_id, vo2_max.vo2_max)
