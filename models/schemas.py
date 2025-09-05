from typing import Any, Dict, List, Literal, Optional
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, field_validator
import re

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"

class Book(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="The Great Gatsby")
    genre: Literal["fiction", "non-fiction"] = Field(..., example="fiction")
    price: float = Field(..., gt=0, description="Price must be greater than 0", example=12.99)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        return v.strip()

class BookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, example="Updated Book Name")
    genre: Optional[Literal["fiction", "non-fiction"]] = Field(None, example="fiction")
    price: Optional[float] = Field(None, gt=0, description="Price must be greater than 0", example=15.99)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        return v.strip() if v else v

class BookResponse(BaseModel):
    book_id: str
    name: str
    genre: str
    price: float
    created_at: str
    updated_at: str

class HealthResponse(BaseModel):
    status: str
    database: str
    connection: str
    database_name: str
    postgresql_version: str
    environment: str
    response_time_ms: float

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    status_code: int

class SuccessResponse(BaseModel):
    message: str
    status_code: int
    data: Optional[dict] = None

class UploadedFileInfo(BaseModel):
    original_filename: str
    s3_key: str
    file_url: str
    file_size: int
    content_type: str

class UploadError(BaseModel):
    filename: str
    error: str
    status_code: int

class MultipleFileUploadResponse(BaseModel):
    uploaded_files: List[UploadedFileInfo]
    total_uploaded: int
    total_failed: int
    errors: Optional[List[UploadError]] = None
    message: str

class FileUploadRecord(BaseModel):
    id: int
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    content_type: str
    file_content: Optional[str] = None
    score: Optional[float] = 0.0
    folder_path: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    upload_ip: Optional[str] = None
    upload_status: str = "success"
    created_at: str
    updated_at: str

class FileUploadListResponse(BaseModel):
    data: List[FileUploadRecord]
    total_count: int
    page: int
    limit: int
    total_pages: int

class DeleteFileResponse(BaseModel):
    message: str
    deleted_key: str
    success: bool

class UserBase(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    role: UserRole = Field(default=UserRole.USER)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain at least one special character')
        return v

class UserUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str

class TokenData(BaseModel):
    user_id: int
    email: str
    role: UserRole

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordReset(BaseModel):
    token: str
    new_password: str

class UserListResponse(BaseModel):
    users: List[UserResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int