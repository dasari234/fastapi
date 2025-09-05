# config.py
"""
Configuration module for environment variables and application settings.
"""

import os
import secrets
from dotenv import load_dotenv

# Constants
DEFAULT_ENVIRONMENT = "production"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_AWS_REGION = "us-east-1"
MAX_FILE_SIZE_MB = 100
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

# Load environment variables from .env file
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")
# Convert postgresql:// to postgres:// for asyncpg compatibility
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://")

# Application settings
ENVIRONMENT = os.getenv("ENVIRONMENT", DEFAULT_ENVIRONMENT)
DEBUG = ENVIRONMENT == "development"
LOG_LEVEL = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
VERSION = "2.0.0"

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", DEFAULT_AWS_REGION)
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# File upload settings
ALLOWED_EXTENSIONS = {
    "image": ["jpg", "jpeg", "png", "gif", "webp"],
    "document": ["pdf", "doc", "docx", "txt", "csv", "xlsx"],
    "video": ["mp4", "mov", "avi", "mkv"],
    "audio": ["mp3", "wav", "ogg"],
}

# SQLAlchemy configuration
SQLALCHEMY_DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://")
POOL_SIZE = 5
MAX_OVERFLOW = 10
POOL_TIMEOUT = 30
POOL_RECYCLE = 1800