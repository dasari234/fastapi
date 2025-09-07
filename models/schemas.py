import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, validator
from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

Base = declarative_base()

class StandardResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int

    class Config:
        from_attributes = True
class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"

# SQLAlchemy Models

class LoginHistory(Base):
    __tablename__ = "login_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    login_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    login_status = Column(String(20), default="success", nullable=False) 
    failure_reason = Column(String(255), nullable=True) 
    
    user = relationship("User", back_populates="login_history")
    
class LoginHistoryResponse(BaseModel):
    id: int
    login_time: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    login_status: str
    failure_reason: Optional[str] = None
    user_id: int
    
    class Config:
        from_attributes = True
        
class LoginStatsResponse(BaseModel):
    total_logins: int
    last_login: Optional[datetime] = None
    successful_logins: int
    failed_logins: int

class UserLoginHistoryResponse(BaseModel):
    user_id: int
    email: str
    login_history: List[LoginHistoryResponse]
    stats: LoginStatsResponse
class User(Base):
    __tablename__ = "users"
    __allow_unmapped__ = True
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    login_history = relationship("LoginHistory", back_populates="user", cascade="all, delete-orphan")

class BookModel(Base):
    __tablename__ = "books"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    genre = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class FileUploadRecord(Base):
    __tablename__ = "file_uploads"
    
    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    s3_key = Column(String(512), unique=True, index=True, nullable=False)
    s3_url = Column(Text, nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False)
    file_content = Column(Text, nullable=True)
    score = Column(Float, default=0.0)
    folder_path = Column(String(255), nullable=True)
    user_id = Column(String(50), nullable=True)
    file_metadata = Column(JSON, nullable=True)
    upload_ip = Column(String(45), nullable=True)
    upload_status = Column(String(20), default="success", nullable=False)
    
    processing_time_ms = Column(Float, default=0.0)  
    version = Column(Integer, default=1) 
    is_current_version = Column(Boolean, default=True) 
    parent_version_id = Column(Integer, ForeignKey("file_uploads.id", ondelete="SET NULL"), nullable=True)
    
    previous_versions = relationship("FileUploadRecord", 
                                   foreign_keys=[parent_version_id],
                                   remote_side=[id],
                                   backref="next_versions")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Index for better performance
    __table_args__ = (
        Index('ix_file_upload_user_id', 'user_id'),
        Index('ix_file_upload_s3_key', 's3_key'),
        Index('ix_file_upload_version', 'version'),
        Index('ix_file_upload_current_version', 'is_current_version'),
        Index('ix_file_upload_s3_key_version', 's3_key', 'version', unique=True),
    )

# Pydantic Models for API
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

class MultipleFileUploadResponse(StandardResponse):
    uploaded_files: Optional[List[UploadedFileInfo]] = None
    total_uploaded: int = 0
    total_failed: int = 0
    errors: Optional[List[UploadError]] = None

class FileUploadRecordResponse(BaseModel):
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
    data: Optional[List[Dict[str, Any]]] = None
    total_count: int = 0
    page: int = 1
    limit: int = 100
    total_pages: int = 1

class DeleteFileResponse(BaseModel):
    deleted_key: Optional[str] = None

# Renamed Pydantic User models to avoid conflicts
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
    
class TokenWithLoginInfo(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True
        

class UserResponseData(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True

class UserListResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any] 
    status_code: int

    class Config:
        from_attributes = True
        
        
class HealthResponse(BaseModel):
    success: bool = Field(..., description="Whether the health check was successful")
    status: str = Field(..., description="Overall status (healthy/unhealthy)")
    database: str = Field(..., description="Database type")
    connection: str = Field(..., description="Connection status")
    database_name: Optional[str] = Field(None, description="Database name")
    postgresql_version: Optional[str] = Field(None, description="PostgreSQL version")
    environment: str = Field(..., description="Environment name")
    response_time_ms: float = Field(..., description="Response time in milliseconds")
    error: Optional[str] = Field(None, description="Error message if any")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        from_attributes = True

class SimpleHealthResponse(BaseModel):
    success: bool
    status: str
    service: str
    message: Optional[str] = None
    error: Optional[str] = None
    status_code: int

    class Config:
        from_attributes = True

class DBHealthResponse(BaseModel):
    success: bool
    status: str
    message: str
    error: Optional[str] = None
    status_code: int

    class Config:
        from_attributes = True
        
class UploadRecordResponse(BaseModel):
    id: int
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    content_type: str
    file_content: Optional[str] = None
    score: float
    folder_path: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    upload_ip: Optional[str] = None
    upload_status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True

class UploadListResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]  
    error: Optional[str] = None
    status_code: int

    class Config:
        from_attributes = True
        
class FileVersionInfo(BaseModel):
    id: int
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    content_type: str
    score: float
    processing_time_ms: float
    version: int
    is_current_version: bool
    parent_version_id: Optional[int] = None
    user_id: str
    created_at: Optional[str] = None
    upload_status: str

class FileVersionHistoryResponse(StandardResponse):
    data: Optional[Dict[str, Any]] = None 

class FileRestoreResponse(StandardResponse):
    data: Optional[Dict[str, Any]] = None