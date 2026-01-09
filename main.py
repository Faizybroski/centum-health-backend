# import os
# os.makedirs("logs", exist_ok=True)
import os
import logging

LOG_DIR = "/tmp/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/app.log"),
        logging.StreamHandler(),  # 👈 important for Vercel dashboard
    ],
)


from pydantic import ValidationError
from motor.motor_asyncio import AsyncIOMotorClient
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from common.config import settings
from routers import authentication
from routers import user_profile
from routers import health_assessment
from routers import document_upload 
from routers.admin import admin_console
from routers import contact
from routers import faq
from common.exception_handlers import (
    http_exception_handler,
    general_exception_handler,
    pydantic_validation_exception_handler,
    rate_limit_handler
)
from common.rate_limiter import limiter
from common.config import logger
from slowapi.errors import RateLimitExceeded
from common.security import EncryptedDatabase


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to MongoDB...")
    mongo_client = AsyncIOMotorClient(settings.MONGO_URI)
    raw_db = mongo_client.get_default_database()
    app.state.db = EncryptedDatabase(raw_db, encrypted_collections=["users", "document_uploads", "user_reports"]) 
    # app.state.db = mongo_client.get_default_database()

    yield
    logger.info("Closing MongoDB connection...")
    mongo_client.close()

app = FastAPI(lifespan=lifespan)


app.mount("/static", StaticFiles(directory="static"), name="static")

app.state.limiter = limiter


# Add exception handlers for consistent response format
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,  # Allow cookies to be sent
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Include all routers
app.include_router(authentication.router, prefix="/api/v1")
app.include_router(user_profile.router, prefix="/api/v1")
app.include_router(health_assessment.router, prefix="/api/v1")
app.include_router(document_upload.router, prefix="/api/v1") 
app.include_router(admin_console.router, prefix="/api/v1")
app.include_router(contact.router, prefix="/api/v1")
app.include_router(faq.router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return {"message": "API is running"}
