from importlib.metadata import files
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Form
from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from common.jwt_auth import get_current_user
from models.document import DocumentMetadata, DocumentResponse
from services.document_service import upload_documents, get_documents, get_secure_blob_file_url
from common.db import get_db

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload", response_model=List[DocumentMetadata])
async def upload_document(
    user_id=Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
    files: List[UploadFile] = File(...),
        # DEV
    report_category: str = Form(...),
    report_title: str = Form(...),
    report_date: str = Form(...),
    report_notes: str | None = Form(None),
):
    return await upload_documents(user_id,db ,files=files, report_category=report_category, report_title=report_title, report_date=report_date, report_notes=report_notes)


# Get the documents of user
@router.get("/get-documents", response_model=List[DocumentResponse])
async def get_user_documents(
    user_id=Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    return await get_documents(db, user_id)



@router.get("/secure-file/{blob_name:path}")
async def get_secure_blob_url(blob_name: str, user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await get_secure_blob_file_url(blob_name, user, db)


# @router.get("/download-decrypted")
# async def download_decrypted_file(blob_url: str):
#     try:
#         # Step 1: Get blob client from URL
#         blob_client = BlobClient.from_blob_url(blob_url)

#         # Step 2: Download encrypted file from blob
#         stream = blob_client.download_blob()
#         encrypted_data = stream.readall()

#         # Step 3: Decrypt the file
#         decrypted_data = decrypt_data_aes(encrypted_data, AES_KEY, AES_IV)

#         # Step 4: Stream decrypted PDF
#         return StreamingResponse(io.BytesIO(decrypted_data), media_type="application/pdf")
    
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Decryption failed: {str(e)}")