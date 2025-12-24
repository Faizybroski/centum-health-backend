import os
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import UploadFile, HTTPException, File, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from models.document import DocumentMetadata
from common.utils import upload_to_azure_blob
from fastapi.responses import JSONResponse
from bson import json_util, ObjectId
from data_processing.ocr import analyze_report
from common.config import logger, settings
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from io import BytesIO
from PyPDF2 import PdfReader


# UPLOAD_DIR = "uploaded_documents"
# os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_upload_dir() -> str:
    """
    Returns a writable upload directory.
    - Vercel: /tmp (ephemeral)
    - Local / VPS: project directory
    """
    is_vercel = os.getenv("VERCEL") == "1"

    upload_dir = (
        "/tmp/uploaded_documents"
        if is_vercel
        else "uploaded_documents"
    )

    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

# Allowed file types
ALLOWED_CONTENT_TYPES = {
    "application/pdf"
}

MAX_FILE_SIZE_MB = 5  # 5MB limit
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024  # Convert MB to Bytes
MAX_FILES_ALLOWED = 5  # Maximum files allowed


# Helper function to validate file size
def format_file_size(size_in_bytes: int) -> str:
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024 ** 2:
        return f"{size_in_bytes / 1024:.2f} KB"
    elif size_in_bytes < 1024 ** 3:
        return f"{size_in_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_in_bytes / (1024 ** 3):.2f} GB"


async def upload_documents(
    user_id: str,
    db: AsyncIOMotorDatabase,
    files: List[UploadFile] = File(...)
):
    try:
        if len(files) > MAX_FILES_ALLOWED:
            return JSONResponse(
                content={"message": f"You can only upload up to {MAX_FILES_ALLOWED} files at a time"},
                status_code=status.HTTP_400_BAD_REQUEST
            )

        document_ids = []

        for file in files:
            if file.content_type not in ALLOWED_CONTENT_TYPES:
                return JSONResponse(
                    content={"message": "Invalid file type"},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Read and validate file size
            file.file.seek(0, os.SEEK_END)
            file_size = file.file.tell()
            file.file.seek(0)

            if file_size == 0:
                return JSONResponse(
                    content={"message": "Empty file is not allowed"},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if file_size > MAX_FILE_SIZE_BYTES:
                return JSONResponse(
                    content={"message": f"File exceeds max allowed size of {MAX_FILE_SIZE_MB} MB"},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            file_bytes = await file.read()
            file_stream = BytesIO(file_bytes)
            # check corrupted file 
            # Optional: check corruption
            try:
                if file.content_type == "application/pdf":
                    PdfReader(file_stream).pages[0]
                file_stream.seek(0)
            except Exception as e:
                logger.error(f"Corrupted PDF: {file.filename} → {e}")
                return JSONResponse(
                    content={"message": f"File '{file.filename}' appears to be corrupted or unreadable."},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Generate unique filename
            extension = os.path.splitext(file.filename)[1]
            unique_filename = f"{uuid.uuid4()}{extension}"
            container_name = settings.AZURE_STORAGE_CONTAINER_NAME

            # 📂 Save local copy (temporary)
            #  #  ----------------------------------------    DEVELOPMENT COMMENT --------------------
            # local_path = os.path.join(UPLOAD_DIR, unique_filename)
            # os.makedirs(UPLOAD_DIR, exist_ok=True)
            upload_dir = get_upload_dir()
            local_path = os.path.join(upload_dir, unique_filename)
            blob_name = f"{user_id}/{unique_filename}"

            with open(local_path, "wb") as buffer:
                buffer.write(file_bytes)
            file.file.seek(0)  # Reset pointer
            
            # Upload to Azure Blob
            blob_url = await upload_to_azure_blob(file, container_name, blob_name)

            # Create document metadata
            document_data = {
                "user_id": ObjectId(user_id),
                "file_name": file.filename,
                # -------------------------------   DEVELOPMENT COMMENT   -----------------------
                # "local_path": local_path,
                "path": blob_url,
                "blob_name": blob_name,
                "size": format_file_size(file_size),
                "content_type": file.content_type,
                "extension": extension,
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }

            result = await db.documents.insert_one(document_data)
            document_ids.append(result.inserted_id)

        # Process OCR (optional, as per your flow)
        await ocr_documents(db, user_id, document_ids)

        # Delete local copies after OCR
        docs = await db.documents.find({"user_id": ObjectId(user_id), "_id": {"$in": document_ids}}).to_list(length=None)
        respon_documents = []
        
        for doc in docs:
            if "local_path" in doc and os.path.exists(doc["local_path"]):
                os.remove(doc["local_path"])

            doc["id"] = str(doc["_id"])
            del doc["_id"]
            respon_documents.append(DocumentMetadata(**doc))

        return respon_documents

    except Exception as e:
        print("Error uploading documents:", e)
        logger.error(f"Error uploading documents:{e}")
        return JSONResponse(
            content={"message": "Error uploading documents"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Get the documents of user
async def get_documents(db: AsyncIOMotorDatabase, user_id: str):
    documents = await db.documents.find(
        {"user_id": ObjectId(user_id)},
        {"file_name": 1, "file_type": 1, "size": 1, "content_type": 1, "extension": 1, "status": 1}).to_list(length=None)
   
    documents = json.loads(json_util.dumps(documents))
    if not documents:
        return JSONResponse(content={"message": "Documents not found", "data": []}, status_code=status.HTTP_200_OK)
    return JSONResponse(content={"message": "Documents fetched successfully", "data": documents}, status_code=status.HTTP_200_OK)


# Ocr the documents and store the data in documents collection
async def ocr_documents(db: AsyncIOMotorDatabase, user_id: str, document_ids: List[ObjectId]):
    try:
        logger.info("OCR started")
        documents_collection = db.documents
        
        # Step 1: Fetch pending documents for the user
        pending_docs_cursor = documents_collection.find({
            "_id": {"$in": document_ids},
            "user_id": ObjectId(user_id),
            "status": "pending"
        })

        pending_documents = await pending_docs_cursor.to_list(length=None)
        
        if not pending_documents:
            return {"message": "No pending documents to process."}

        for doc in pending_documents:
            doc_id = doc["_id"]
            file_path = doc["local_path"]
            
            try:
                # Step 1: Analyze document
                extracted_data = await analyze_report(file_path)
                # print("Extracted data:", extracted_data)
                if not extracted_data:
                    await documents_collection.update_one(
                        {"_id": doc_id},
                        {"$set": {"status": "failed", "message": "Document Extracted data is empty."}}
                    )
                    logger.error("Lab results is empty from document.")
                    # raise Exception("Document Extracted data is empty.")
                    continue

                # Store patient_info and lab_results in user_reports (without summary)
                await documents_collection.find_one_and_update(
                    {
                        "_id": doc_id,
                        "user_id": ObjectId(user_id),
                    },
                    {
                        "$set": {
                            "lab_results": extracted_data,
                            "status": "ready",
                            "ocr_done": True,
                            "updated_at": datetime.now(timezone.utc)
                        }
                    },
                )
                
            except Exception as e:
                print('error', e)
                await documents_collection.update_one(
                    {"_id": doc_id},
                    {"$set": {"status": "failed", "message": str(e)}}
                )
                logger.error("Error extracted document: {e}")
        logger.info("OCR completed")
        return {"message": "User documents analyzed and extracted data stored in user report."}
    except Exception as e:
        logger.error(f"Error in ocr_documents: {e}")
        return {"message": "Error in ocr_documents: ", "error": str(e)}


async def get_secure_blob_file_url(blob_name: str, user_id: str, db: AsyncIOMotorDatabase):
    # Validate that this blob belongs to the user in your MongoDB
    try:
        doc = await db.documents.find_one({"blob_name": blob_name, "user_id": ObjectId(user_id)})
        if not doc:
            return JSONResponse(content={"message": "You do not have access to this file."}, status_code=403)

        sas_token = generate_blob_sas(
            account_name=settings.AZURE_STORAGE_ACCOUNT_NAME,
            container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
            blob_name=blob_name,
            account_key=settings.AZURE_STORAGE_ACCOUNT_KEY,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=10)  # valid for 10 min
        )
        # print("SAS token generated: ", sas_token)
        url = f"{settings.AZURE_STORAGE_ACCOUNT_URL}/{settings.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}?{sas_token}"
        return JSONResponse(content={"url": url}, status_code=200)
    except Exception as e:
        logger.error("Error in get_secure_blob_file_url: {e}")
        return JSONResponse(content={"message": "Error generating SAS token."}, status_code=500)