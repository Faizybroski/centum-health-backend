import logging
from pydantic_settings import BaseSettings
from pydantic import EmailStr
from typing import Optional
from dotenv import load_dotenv
import sys

load_dotenv(dotenv_path="local.env")

class Settings(BaseSettings):
    MONGO_URI: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    EMAIL_HOST: str
    EMAIL_PORT: int = 587
    EMAIL_USERNAME: str
    EMAIL_PASSWORD: str
    EMAIL_FROM: EmailStr
    EMAIL_FROM_NAME: str
    FRONTEND_BASE_URL: Optional[str] = "http://localhost:3000"
    BACKEND_BASE_URL: Optional[str] = "http://localhost:8002"
    ADMIN_EMAIL: EmailStr
    SUPPORT_EMAIL: EmailStr
    AZURE_AI_DOCUMENT_INTELLIGENCE_ENDPOINT: str
    AZURE_AI_DOCUMENT_INTELLIGENCE_KEY: str
    AZURE_CUSTOM_MODEL_ID: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_VERSION: str
    AZURE_OPENAI_DEPLOYMENT: str
    AZURE_STORAGE_ACCOUNT_URL: str
    AZURE_STORAGE_ACCOUNT_KEY: str
    AZURE_SAS_TOKEN_EXPIRY_MINUTES: int
    # GROK
    AZURE_GROK_DEPLOYMENT: str
    AZURE_GROK_ENDPOINT: str
    AZURE_GROK_API_KEY: str
    RESET_TOKEN_EXPIRY_MINUTES: int
    VERIFICATION_TOKEN_EXPIRY_DAYS: int
    MAX_RESET_ATTEMPTS: int
    RESET_WINDOW_MINUTES: int
    AZURE_STORAGE_ACCOUNT_NAME: str
    AZURE_STORAGE_CONTAINER_NAME: str
    FERNET_KEY: str
    class Config:
        env_file = "local.env"
        env_file_encoding = "utf-8"

settings = Settings()


logging.basicConfig(
    filename="logs/app.log",
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# Create logger
logger = logging.getLogger("centum_logger")
logger.setLevel(logging.INFO)
logger.propagate = False  # ✅ Prevent logs from going to root logger

# File handler
file_handler = logging.FileHandler("logs/app.log")
file_handler.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Silence noisy Azure logs
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)