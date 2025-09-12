"""
Configuration module for environment variables and application settings.
Centralized settings for database, security, AWS, and application behavior.
"""

import os
import secrets
from urllib.parse import urlparse
from dotenv import load_dotenv
from typing import Dict, List, Optional

# Load environment variables
load_dotenv()

#---Constants---

DEFAULT_ENVIRONMENT = "production"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_VERSION = "2.0.0"

MAX_FILE_SIZE_MB = 100
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024  # bytes

#---Database Configuration---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

parsed_url = urlparse(DATABASE_URL)

#---Extract query params---
query_params: Dict[str, str] = {}
if parsed_url.query:
    query_params = dict(
        param.split("=", 1) for param in parsed_url.query.split("&") if "=" in param
    )

#---Handle sslmode separately---
ssl_mode: str = query_params.pop("sslmode", "prefer")
if parsed_url.hostname in {"localhost", "127.0.0.1"}:
    ssl_mode = "prefer"

#---Reconstruct DB URL without sslmode---
new_query = "&".join([f"{k}={v}" for k, v in query_params.items()])
clean_url = parsed_url._replace(query=new_query or None).geturl()

#---Ensure correct driver---
if clean_url.startswith("postgres://"):
    clean_url = clean_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif clean_url.startswith("postgresql://"):
    clean_url = clean_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif not clean_url.startswith("postgresql+asyncpg://"):
    clean_url = "postgresql+asyncpg://" + clean_url.split("://", 1)[1]

SQLALCHEMY_DATABASE_URL = clean_url
SSL_MODE = ssl_mode

#---SQLAlchemy engine settings---
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", 5))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", 10))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", 30))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", 1800))

#---Application Settings---

ENVIRONMENT = os.getenv("ENVIRONMENT", DEFAULT_ENVIRONMENT)
DEBUG: bool = ENVIRONMENT == "development"
LOG_LEVEL = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
VERSION = os.getenv("APP_VERSION", DEFAULT_VERSION)

#---AWS / S3 Configuration---
AWS_ACCESS_KEY_ID: Optional[str] = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", DEFAULT_AWS_REGION)
S3_BUCKET_NAME: Optional[str] = os.getenv("S3_BUCKET_NAME")

#---Security / JWT Configuration---
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

#---File Upload Settings---
ALLOWED_EXTENSIONS: Dict[str, List[str]] = {
    "image": ["jpg", "jpeg", "png", "gif", "webp"],
    "document": ["pdf", "doc", "docx", "txt", "csv", "xlsx"],
    "video": ["mp4", "mov", "avi", "mkv"],
    "audio": ["mp3", "wav", "ogg"],
}

#---CORS / Origins---
ALLOWED_ORIGINS: List[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

#---Document Scoring / Chunking---
MAX_CONTENT_LENGTH_FOR_SCORING = 1024 * 1024  # 1 MB
CHUNK_SIZE = 8192  # 8 KB
