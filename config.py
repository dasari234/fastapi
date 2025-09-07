"""
Configuration module for environment variables and application settings.
"""

import os
import secrets
from urllib.parse import urlparse

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

# Parse the database URL to handle SSL mode properly
parsed_url = urlparse(DATABASE_URL)
query_params = {}
if parsed_url.query:
    query_params = dict(param.split('=') for param in parsed_url.query.split('&') if '=' in param)

# Remove sslmode from query parameters if present and handle it separately
ssl_mode = query_params.pop('sslmode', 'prefer')
if 'localhost' in parsed_url.hostname or '127.0.0.1' in parsed_url.hostname:
    ssl_mode = 'prefer'

# Reconstruct the URL without sslmode in query
new_query = '&'.join([f"{k}={v}" for k, v in query_params.items()])
clean_url = parsed_url._replace(query=new_query if new_query else None).geturl()

# Ensure we're using the asyncpg driver
if clean_url.startswith('postgres://'):
    clean_url = clean_url.replace('postgres://', 'postgresql+asyncpg://')
elif clean_url.startswith('postgresql://'):
    clean_url = clean_url.replace('postgresql://', 'postgresql+asyncpg://')
elif not clean_url.startswith('postgresql+asyncpg://'):
    clean_url = 'postgresql+asyncpg://' + clean_url.split('://', 1)[1]
    
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
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# File upload settings
ALLOWED_EXTENSIONS = {
    "image": ["jpg", "jpeg", "png", "gif", "webp"],
    "document": ["pdf", "doc", "docx", "txt", "csv", "xlsx"],
    "video": ["mp4", "mov", "avi", "mkv"],
    "audio": ["mp3", "wav", "ogg"],
}

# SQLAlchemy configuration
SQLALCHEMY_DATABASE_URL = clean_url
POOL_SIZE = 5
MAX_OVERFLOW = 10
POOL_TIMEOUT = 30
POOL_RECYCLE = 1800

# SSL configuration for database
SSL_MODE = ssl_mode