from bson import ObjectId
from datetime import datetime, timezone
from typing import Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status, BackgroundTasks

from data_processing.summary_genrater import generate_clinical_summary_grok
from models.health_assessment import (
        HealthFormStep1Model, HealthFormStep2Model, HealthFormStep3Model, HealthFormStep4Model
    )
from common.config import logger
from data_processing.biomarkers_range import biomarker_with_description, section_to_biomarkers
from data_processing.calculate_age import calculate_biological_age
from data_processing.report_genration import report_generation_pipeline
from data_processing.report_compare import compare_by_bands, generate_comparison_summary_using_grok


# Save Health Assessment Step
async def save_health_assessment_step(
    db: AsyncIOMotorDatabase,
    user_id: str,
    step_number: int,
    form_data: Dict[str, Any]
):
    try:
        logger.info(f"Saving health assessment step {step_number} for user {user_id}")
        if not (1 <= step_number <= 4):
            return JSONResponse(content={"message": "Invalid step number."}, status_code=status.HTTP_400_BAD_REQUEST)

        responses_coll = db["health_assessment_responses"]
        now = datetime.now(timezone.utc)

        step_models = {
            1: (HealthFormStep1Model, "step_1_answers", "step_1"),
            2: (HealthFormStep2Model, "step_2_answers", "step_2"),
            3: (HealthFormStep3Model, "step_3_answers", "step_3"),
            4: (HealthFormStep4Model, "step_4_answers", "step_4"),
        }
        if step_number in step_models:
            model_cls, answer_key, step_key = step_models[step_number]
            try:
                validated = model_cls(**form_data)
            except Exception as e:
                raise  # propagate the original ValidationError so the custom handler is used
            update_data = {
                answer_key: validated.dict(exclude_none=True),
                "last_completed_step": step_key,
                "updated_at": now
            }
        else:
            return JSONResponse(content={"message": "Invalid step number."}, status_code=status.HTTP_400_BAD_REQUEST)

        # Try to update first
        result = await responses_coll.update_one(
            {"user_id": ObjectId(user_id)},
            {"$set": update_data, "$setOnInsert": {"created_at": now}},
            upsert=True
        )
        
        if result.upserted_id or result.modified_count > 0:
            # Check if all steps are completed and update is_health_assessment_complete flag
            updated_doc = await responses_coll.find_one({"user_id": ObjectId(user_id)})
            completed_steps = []
            for i in range(1, 5):
                step_field = f"step_{i}_answers"
                if updated_doc and step_field in updated_doc and updated_doc[step_field]:
                    completed_steps.append(i)
            
            is_health_assessment_complete = len(completed_steps) == 4
            
            # Update the is_health_assessment_complete flag in the database
            await responses_coll.update_one(
                {"user_id": ObjectId(user_id)},
                {"$set": {"is_health_assessment_complete": is_health_assessment_complete, "updated_at": now}}
            )

            # Calculate biological age if all steps are completed
            user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
            chronological_age = user_doc.get("chronological_age", 0)
            
            if is_health_assessment_complete:
                biological_age_object = await calculate_biological_age(db, user_id, chronological_age)
                await db.users.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {
                        "biological_age": biological_age_object['biological_age'], 
                        "adjustment_cap": biological_age_object['adjustment_cap'], 
                        "risk_points": biological_age_object['risk_points'], 
                        "risk_percent": biological_age_object['risk_percent'], 
                        "raw_biological_age": biological_age_object['raw_biological_age'], 
                        "max_negative_cap": biological_age_object['max_negative_cap'], 
                        "max_positive_cap": biological_age_object['max_positive_cap'], 
                        "sum_weights": biological_age_object['sum_weights'], 
                        "s_max": biological_age_object['s_max'], 
                        "updated_at": now}}
                )

            return JSONResponse(content={
                "message": "Health Assessment saved successfully", 
                "current_step": step_number,
                "is_health_assessment_complete": is_health_assessment_complete,
                "completed_steps": completed_steps
            }, status_code=status.HTTP_200_OK)
        else:
            return JSONResponse(content={"message": "Failed to save step data."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.error(f"Error saving health assessment step: {str(e)}")
        return JSONResponse(content={"message": "Failed to save health assessment step."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


async def get_health_assessment_form_step(db: AsyncIOMotorDatabase, user_id: str, step_number: int):
    """
    Fetch form structure for a specific step, merge with user answers, and return merged result.
    Injects the answer into each field (including "{key}_other_text" for checkbox_group fields).
    """
    try:
        form_coll = db["health_assessment_form"]
        doc_id = f"health_form_step_{step_number}"

        pipeline = [
            {"$match": {"_id": doc_id}},
            {"$lookup": {
                "from": "health_assessment_responses",
                "let": {"user_id": ObjectId(user_id)},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$user_id", "$$user_id"]}}},
                    {"$project": {f"step_{step_number}_answers": 1, "_id": 0}}
                ],
                "as": "user_answer"
            }},
            {"$addFields": {
                "user_answers": {"$ifNull": [{"$arrayElemAt": ["$user_answer", 0]}, {}]}
            }},
            {"$addFields": {
                "sections": {
                    "$map": {
                        "input": "$sections",
                        "as": "section",
                        "in": {
                            "$mergeObjects": [
                                "$$section",
                                {
                                    "fields": {
                                        "$map": {
                                            "input": "$$section.fields",
                                            "as": "field",
                                            "in": {
                                                "$mergeObjects": [
                                                    "$$field",
                                                    {
                                                        "answer": {
                                                            "$let": {
                                                                "vars": {
                                                                    "answerPair": {
                                                                        "$first": {
                                                                            "$filter": {
                                                                                "input": {
                                                                                    "$objectToArray": f"$user_answers.step_{step_number}_answers"
                                                                                },
                                                                                "as": "pair",
                                                                                "cond": {
                                                                                    "$eq": ["$$pair.k", "$$field.key"]
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                },
                                                                "in": {"$ifNull": ["$$answerPair.v", ""]}
                                                            }
                                                        }
                                                    },
                                                    {
                                                        "$cond": [
                                                            {"$eq": ["$$field.type", "checkbox_group"]},
                                                            {
                                                                "$let": {
                                                                    "vars": {
                                                                        "otherPair": {
                                                                            "$first": {
                                                                                "$filter": {
                                                                                    "input": {
                                                                                        "$objectToArray": f"$user_answers.step_{step_number}_answers"
                                                                                    },
                                                                                    "as": "pair",
                                                                                    "cond": {
                                                                                        "$eq": [
                                                                                            "$$pair.k",
                                                                                            {"$concat": ["$$field.key", "_other_text"]}
                                                                                        ]
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    },
                                                                    "in": {
                                                                        "$arrayToObject": [[
                                                                            {
                                                                                "k": {"$concat": ["$$field.key", "_other_text"]},
                                                                                "v": {"$ifNull": ["$$otherPair.v", ""]}
                                                                            }
                                                                        ]]
                                                                    }
                                                                }
                                                            },
                                                            {}
                                                        ]
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }}
        ]

        agg_result = await form_coll.aggregate(pipeline).to_list(length=None)
        if not agg_result:
            return JSONResponse(content={"message": "Form step not found."}, status_code=status.HTTP_404_NOT_FOUND)

        form = agg_result[0]
        form.pop("user_answer", None)
        form.pop("user_answers", None)

        return JSONResponse(content={
            "form": form,
            "step_number": step_number,
        }, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching form step: {str(e)}")
        return JSONResponse(content={"message": "Failed to fetch form step."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Create report
async def create_report(db: AsyncIOMotorDatabase, user_id: str, report_title: str, document_ids: List[str], background_tasks: BackgroundTasks):
    try:
        document_ids = [ObjectId(doc_id) for doc_id in document_ids]
        documents = await db.user_reports.find({"report_title": report_title, "user_id": ObjectId(user_id)})
       
        if documents:
            return JSONResponse(content={"message": "Report title already exists."}, status_code=400)
    
        # Check if any of the document_ids already used in any report for the user
        conflict_report = await db.user_reports.find_one({
            "user_id": ObjectId(user_id),
            "document_ids": {"$in": document_ids}
        })

        if conflict_report:
            logger.info(f"Report already exists for the selected documents for user {user_id}")
            return JSONResponse(content={"message": "Report already exists for the selected documents."}, status_code=400)
        
        report_data = {
            "user_id": ObjectId(user_id),
            "report_title": report_title,
            "document_ids": document_ids,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        report = await db.user_reports.insert_one(report_data)
        report_id = report.inserted_id
        
        background_tasks.add_task(generate_and_upsert_clinical_summary, db, user_id, document_ids, report_id)
        return JSONResponse(content={"report_id": str(report_id), "message": "Report created successfully. Analysis started."}, status_code=status.HTTP_200_OK)
    except Exception as e:
        print("Error creating report:", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------
async def get_biomarkers_for_test(report: dict) -> dict:
    # metadata fields we want to drop
    metadata_keys = {
        "patient name", "patient id", "DOB", "age", "collection date",
        "report date", "laboratory", "gender", "referring doctor", "fasting status"
    }

    biomarkers = {}

    for key, value in report.items():
        if key in metadata_keys:
            continue  # skip metadata

        if not value:
            continue  # skip None / empty

        # most entries are a list of dicts
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
            first_entry = value[0]
            result = first_entry.get("Result") or first_entry.get("Results")
            units = first_entry.get("Units")
            if result:  # only include if we have a result
                biomarkers[key] = {
                    "result": str(result),
                    "units": units if units else ""
                }
        # some fields may directly be dicts (rare)
        elif isinstance(value, dict):
            result = value.get("Result") or value.get("Results")
            units = value.get("Units")
            if result:
                biomarkers[key] = {
                    "result": str(result),
                    "units": units if units else ""
                }

    return biomarkers


# New function: generate summary from extracted data in user_reports and upsert
async def generate_and_upsert_clinical_summary(db: AsyncIOMotorDatabase, user_id: str, document_ids: list, report_id: ObjectId):
    reports_collection = db["user_reports"]
    documents_collection = db["documents"]
    users_collection = db["users"]
    
    document_ids = [ObjectId(doc_id) for doc_id in document_ids]
    report_id = ObjectId(report_id)
    
    report = await reports_collection.find_one({"_id": report_id, "user_id": ObjectId(user_id), "status": "ready"})
    if report:
        logger.info(f"Report for {report_id} is already ready for analysis for user {user_id}")
        return 
    
    # Fetch all related documents for the user
    documents_data = await documents_collection.find({
        "user_id": ObjectId(user_id),
        "_id": {"$in": document_ids},
        "ocr_done": True
    }).to_list(length=None)

    documents_data = sorted(
        documents_data,
        key=lambda d: d.get("lab_results", {}).get("report date", "")
    )
    if not documents_data:
        logger.info(f"No documents found for user {user_id} for report {report_id}")
        return 
    
    # Combine all lab_results into one unique dictionary
    combined_lab_results = {}

    # Step 1: collect the last seen value for every biomarker
    for doc in documents_data:
        lab = doc.get("lab_results", {})
        for k, v in lab.items():
            if k != "report date":
                if v is not None and v != "":   # only update if value is valid
                    combined_lab_results[k] = v

    latest_lab = documents_data[-1].get("lab_results", {})
    report_date = latest_lab.get("report date", "")
    
    if not combined_lab_results:
        await reports_collection.update_one(
            {"_id": report_id},
            {"$set": {"status": "failed", "message": "Missing lab results."}}
        )
        return 
    
    user_info = await users_collection.find_one({"_id": ObjectId(user_id)},{"gender": 1, "chronological_age": 1})

    gender = user_info.get("gender", "")
    age = user_info.get("chronological_age", 0)
    questionnaire = await get_questionnaire(db, user_id)
    test_results_for_llm = await get_biomarkers_for_test(combined_lab_results)  

    try:
        # summary_obj = await generate_clinical_summary_grok(gender, test_results_for_llm, questionnaire)
        summary_obj = await report_generation_pipeline(gender, age, test_results_for_llm, questionnaire)
        if not summary_obj:
            await reports_collection.update_one(
            {"_id": report_id},
            {"$set": {"status": "failed", "message": "Failed to generate summary."}}
            )
            logger.error(f"Failed to generate summary for report {report_id} for user {user_id}")
            return 
        
        # Upsert report summary into user_reports
        upsert_success = await upsert_report_details(
            reports_collection, report_id, user_id,
            combined_lab_results, summary_obj, gender, age, report_date
        )

        if not upsert_success:
            logger.error(f"Failed to upsert report summary for report {report_id} for user {user_id}")
            return 
        
        # Mark each document as processed
        await documents_collection.update_many(
            {"_id": {"$in": document_ids}},
            {"$set": {"status": "processed", "summary_done": True}}
        )
        logger.info(f"Summary generated and upserted successfully for report {report_id} for user {user_id}")
        return {"message": "Summary generated and upserted successfully."}

    except Exception as e:
        # print("Error generating summary for report {report_id} for user {user_id}: {str(e)}", e)
        logger.error(f"Error generating summary for report {report_id} for user {user_id}: {str(e)}")
        await reports_collection.update_one(
            {"_id": report_id},
            {"$set": {"status": "failed", "message": "Failed to generate summary."}}
        )
        return 


async def map_biomarkers_with_ranges(
    data: Dict[str, Dict],
    gender: str = "male",
    invalid: bool = False

) -> Dict[str, Dict]:
    mapped = {}
    gender_key = "M" if gender.lower().startswith("m") else "F"

    try:
        for biomarker, value_data in data.items():
            if biomarker not in biomarker_with_description:
                continue  # skip if not found in reference dictionary

            ref = biomarker_with_description[biomarker]

            # Check if gender-specific reference range
            if isinstance(ref.get("M"), dict) and isinstance(ref.get("F"), dict):
                gender_ref = ref.get(gender_key, {})
                reference_range = gender_ref.get("reference_range", "N/A")
                unit = gender_ref.get("unit", "")
            else:
                reference_range = ref.get("reference_range", "N/A")
                unit = ref.get("unit", "")

            if invalid:
                mapped[biomarker] = mapped[biomarker] = {
                "value": value_data.get("value", "N/A"),
                "unit": value_data.get("unit", ""),
                "expected_unit": unit,
                "reference_range": reference_range,
                "name": ref.get("name", biomarker.replace("_", " ").title()),
                "description": ref.get("description", ""),
                "reason": value_data.get("reason", "Invalid unit")
            }
            else:
                mapped[biomarker] = {
                "value": value_data.get("value", "N/A"),
                "original_unit": value_data.get("unit", ""),
                "unit": unit,
                "reference_range": reference_range,
                "name": ref.get("name", biomarker.replace("_", " ").title()),
                "description": ref.get("description", "")
            }

        return mapped

    except Exception as e:
        logger.error(f"Error mapping biomarkers: {str(e)}")
        return {}


async def upsert_report_details(reports_collection, report_id, user_id, combined_lab_results, summary_obj, gender, age, report_date) -> bool:
    """
    Upsert report details in the DB. Returns True if successful, False otherwise.
    Handles errors gracefully.
    """
    try:
        counts = summary_obj.get("counts", {})
        summary = summary_obj.get("summary", "")
        good_biomarkers = summary_obj.get("good", {})
        normal_biomarkers = summary_obj.get("normal", {})
        critical_biomarkers = summary_obj.get("critical", {})
        invalid_biomarkers = summary_obj.get("invalid_biomarkers", {})
        lifestyle_recommendations = summary_obj.get("action_plan", {})
        critical_concerns = summary_obj.get("critical_concerns", {})
        section_summary = summary_obj.get("section_summary", {})

        good_biomarkers = await map_biomarkers_with_ranges(good_biomarkers, gender)
        normal_biomarkers = await map_biomarkers_with_ranges(normal_biomarkers, gender)
        critical_biomarkers = await map_biomarkers_with_ranges(critical_biomarkers, gender)
        invalid_biomarkers = await map_biomarkers_with_ranges(invalid_biomarkers, gender, invalid=True)
        
        await reports_collection.find_one_and_update(
            {
                "_id": report_id,
                "user_id": ObjectId(user_id)
            },
            {
                "$set": {
                    "status": "ready",
                    "combined_lab_results": combined_lab_results,
                    "summary": summary,
                    "section_summary": section_summary,
                    "good_biomarkers": good_biomarkers,
                    "normal_biomarkers": normal_biomarkers,
                    "critical_biomarkers": critical_biomarkers,
                    "invalid_biomarkers": invalid_biomarkers,
                    "lifestyle_recommendations": lifestyle_recommendations,
                    "health_score": len(good_biomarkers),
                    "critical_concerns": critical_concerns,
                    "biomarker_counts": counts,
                    "gender": gender,
                    "age": age,
                    "report_date": report_date,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        logger.info("Report details upserted successfully.")
        return True
    except Exception as e:
        logger.error(f"Error upserting report details: {e}")
        return False


# Get user reports
async def get_user_reports(db: AsyncIOMotorDatabase, user_id: str):
    try:
        pipeline = [
            {"$match": {"user_id": ObjectId(user_id)}},
            {"$sort": {"updated_at": -1}},
            {"$project": {
                "_id": 0,
                "id": { "$toString": "$_id" },
                "report_title": 1,
                "status": 1,
                "health_score": 1,
                "summary": 1,
                "report_date": 1,
                "processed_at": {
                    "$dateToString": {
                        "format": "%b %d, %Y",
                        "date": "$updated_at"
                    }
                }
            }}
        ]
        user_reports = await db.user_reports.aggregate(pipeline)
        # user_reports = await user_reports.to_list(length=100)
        content = {
            "data": {"reports": user_reports if user_reports else []},
            "message": "Reports fetched successfully." if user_reports else "No reports found." 
        }
        return JSONResponse(content=content, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching user reports: {e}")
        return JSONResponse(content={"message": "Failed to fetch user reports."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Get user report details
async def get_user_report_details(db: AsyncIOMotorDatabase, user_id: str, report_id: str):
    try:
        pipeline = [
            {"$match": {"_id": ObjectId(report_id), "user_id": ObjectId(user_id)}},
            {"$lookup": {
                "from": "documents",
                "localField": "document_ids",
                "foreignField": "_id",
                "as": "documents_info"
            }},
            {"$project": {
                "_id": 0,
                "id": { "$toString": "$_id" },
                "report_title": 1,
                "status": 1,
                "health_score": 1,
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
                "documents": { "$map": { "input": "$documents_info", "as": "doc", "in": "$$doc.file_name" } },
                "good_biomarkers": 1,
                "normal_biomarkers": 1,
                "critical_biomarkers": 1,
                "invalid_biomarkers": 1,
                "lifestyle_recommendations": 1,
                "critical_concerns": 1,
                "summary": 1,
                "section_summary": 1,
                "processed_at": {
                    "$dateToString": {
                        "format": "%b %d, %Y",
                        "date": "$updated_at"
                    }
                }
            }}
        ]
        result = await db.user_reports.aggregate(pipeline)
        # result = await agg.to_list(length=1)
        if not result:
            return JSONResponse(content={"message": "Report not found."}, status_code=status.HTTP_404_NOT_FOUND)
        return result[0]
    except Exception as e:
        logger.error(f"Error fetching user report details: {e}")
        return JSONResponse(content={"message": "Failed to fetch user report details."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


async def get_questionnaire(db: AsyncIOMotorDatabase, user_id: str):
    try:
        # Merge all step answers (step_1_answers to step_4_answers) from the questionnaire document into a single dict
        questionnaire_doc = await db.health_assessment_responses.find_one({"user_id": ObjectId(user_id)})
        merged_questionnaire = {}
        if questionnaire_doc:
            for i in range(1, 5):
                key = f"step_{i}_answers"
                if key in questionnaire_doc and isinstance(questionnaire_doc[key], dict):
                    merged_questionnaire.update(questionnaire_doc[key])
        return merged_questionnaire
    except Exception as e:
        logger.error(f"Error fetching questionnaire: {e}")
        return {}


# Dashboard data 
async def dashboard_data(db: AsyncIOMotorDatabase, user_id: str):
    try:
        pipeline = [
            # get the latest report
            {"$match": {"user_id": ObjectId(user_id), "status": "ready"}},
            {"$sort": {"updated_at": -1}},
            {"$limit": 1},
            {"$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user_info"
            }},
            {"$project": {
                "_id": 0,
                "id": { "$toString": "$_id" },
                "report_title": 1,
                "status": 1,
                "health_score": 1,
                # Convert ages to strings
                "chronological_age": { "$toString": { "$arrayElemAt": ["$user_info.chronological_age", 0] } },
                "biological_age": { "$toString": { "$arrayElemAt": ["$user_info.biological_age", 0] } },
                "vo2_max": { "$toString": { "$arrayElemAt": ["$user_info.vo2_max", 0] } },
                "good_biomarkers": 1,
                "normal_biomarkers": 1,
                "critical_biomarkers": 1,
                "lifestyle_recommendations": 1,
                "critical_concerns": 1,
                "summary": 1,
                "section_summary": 1
                
            }}
        ]
        result = await db.user_reports.aggregate(pipeline)
        # result = await agg.to_list(length=1)
        content = {
            "data": result[0] if result else [],
            "message": "Data fetched successfully." if result else "No data found."
        }
        return JSONResponse(content=content, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching user report details: {e}")
        return JSONResponse(content={"message": "Failed to fetch user report details."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Compare two reports only
async def compare_two_reports(db: AsyncIOMotorDatabase, user_id: str, report_id_1: str, report_id_2: str):
    try:
        logger.info("Comparing reports between two reports started...")

        # Always sort the reports so order does not matter
        r1, r2 = sorted([ObjectId(report_id_1), ObjectId(report_id_2)], key=lambda x: str(x))

        # Fetch the two reports
        reports = await db.user_reports.find(
            {"_id": {"$in": [r1, r2]}, "user_id": ObjectId(user_id)},
            {
                "good_biomarkers": 1,
                "normal_biomarkers": 1,
                "critical_biomarkers": 1,
                "updated_at": 1,
                "gender": 1,
                "report_date": 1
            }
        )

        if not reports or len(reports) != 2:
            return JSONResponse(content={"message": "Reports not found."}, status_code=status.HTTP_404_NOT_FOUND)

        # Check if comparison already exists (order independent now)
        compare_report = await db.report_comparisons.find_one({
            "user_id": ObjectId(user_id),
            "report_id_1": r1,
            "report_id_2": r2
        })

        if compare_report:
            return JSONResponse(
                content={"message": "Reports already compared.", "summary": compare_report.get("summary")},
                status_code=status.HTTP_200_OK
            )

        # Unpack the reports
        report_1, report_2 = reports[0], reports[1]

        report1_date = report_1.get("report_date") \
            if report_1.get("report_date") \
            else report_1.get("updated_at").strftime("%Y-%m-%d")
        report2_date = report_2.get("report_date") \
            if report_2.get("report_date") \
            else report_2.get("updated_at").strftime("%Y-%m-%d")

        # Run comparison
        result = await compare_by_bands(
            section_to_biomarkers,     # your 16-category dict
            report_old=report_1,
            report_new=report_2,
            date_old=report1_date,
            date_new=report2_date,
            sex=report_1.get("gender", ""),
            consider_only_old_present=True,
        )

        # Generate summary (Azure)
        summary = await generate_comparison_summary_using_grok(result)
        if not summary:
            logger.error(f"Failed to generate comparison summary for reports {report_id_1} and {report_id_2}.")
            return JSONResponse(content={"message": "Failed to generate comparison summary."},
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Store comparison in DB (always stored sorted)
        await db.report_comparisons.insert_one({
            "user_id": ObjectId(user_id),
            "report_id_1": r1,
            "report_id_2": r2,
            "summary": summary,
            "created_at": datetime.now(timezone.utc)
        })

        logger.info("Reports compared successfully.")
        return JSONResponse(content={"message": "Reports compared successfully.", "summary": summary},
                            status_code=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error comparing reports: {e}")
        return JSONResponse(content={"message": "Failed to compare reports."},
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Update vo2 max if not added
async def update_vo2_max_value(db: AsyncIOMotorDatabase, user_id: str, vo2_max: float):
    try:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"vo2_max": vo2_max}}
        )
        return JSONResponse(content={"message": "VO2 max updated successfully."}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error updating VO2 max: {e}")
        return JSONResponse(content={"message": "Failed to update VO2 max."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)