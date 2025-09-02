
"""
Configuration module for environment variables and application settings.
"""

import os

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

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", DEFAULT_AWS_REGION)
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# File upload settings
ALLOWED_EXTENSIONS = {
    "image": ["jpg", "jpeg", "png", "gif", "webp"],
    "document": ["pdf", "doc", "docx", "txt", "csv", "xlsx"],
    "video": ["mp4", "mov", "avi", "mkv"],
    "audio": ["mp3", "wav", "ogg"],
}
