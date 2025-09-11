import re
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, validator


class UserRole(str, Enum):
    """User roles enumeration"""
    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"


class UserBase(BaseModel):
    """Base user model without sensitive data"""
    email: EmailStr = Field(..., description="User email address")
    first_name: str = Field(..., min_length=1, max_length=50, description="First name")
    last_name: str = Field(..., min_length=1, max_length=50, description="Last name")
    role: UserRole = Field(default=UserRole.USER, description="User role")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "role": "user"
            }
        }


class UserCreate(UserBase):
    """User creation model with password validation"""
    password: str = Field(..., min_length=8, max_length=100, description="Password")

    @validator('password')
    def validate_password(cls, v):
        """Validate password strength"""
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

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "role": "user",
                "password": "SecurePassword123!"
            }
        }


class UserUpdate(BaseModel):
    """User update model (partial updates allowed)"""
    first_name: Optional[str] = Field(None, min_length=1, max_length=50, description="First name")
    last_name: Optional[str] = Field(None, min_length=1, max_length=50, description="Last name")
    role: Optional[UserRole] = Field(None, description="User role")
    is_active: Optional[bool] = Field(None, description="Account active status")

    class Config:
        json_schema_extra = {
            "example": {
                "first_name": "John",
                "last_name": "Smith",
                "role": "user",
                "is_active": True
            }
        }


class UserResponse(UserBase):
    """User response model with additional fields"""
    id: int = Field(..., description="User ID")
    is_active: bool = Field(..., description="Account active status")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "role": "user",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z"
            }
        }


class UserResponseData(BaseModel):
    """User data response with login information"""
    id: int = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    first_name: str = Field(..., description="First name")
    last_name: str = Field(..., description="Last name")
    role: str = Field(..., description="User role")
    is_active: bool = Field(..., description="Account active status")
    created_at: Optional[str] = Field(None, description="Account creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "role": "user",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z",
                "last_login": "2023-12-01T10:30:00Z"
            }
        }

  
class LoginHistoryResponse(BaseModel):
    """Login history record"""
    id: int = Field(..., description="Record ID")
    login_time: datetime = Field(..., description="Login timestamp")
    ip_address: Optional[str] = Field(None, description="IP address used for login")
    user_agent: Optional[str] = Field(None, description="User agent string")
    login_status: str = Field(..., description="Login status (success/failed)")
    failure_reason: Optional[str] = Field(None, description="Failure reason if login failed")
    user_id: int = Field(..., description="User ID")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "login_time": "2023-12-01T10:30:00Z",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0...",
                "login_status": "success",
                "failure_reason": None,
                "user_id": 1
            }
        }

class LoginStatsResponse(BaseModel):
    """Login statistics"""
    total_logins: int = Field(..., description="Total login attempts")
    last_login: Optional[datetime] = Field(None, description="Last successful login")
    successful_logins: int = Field(..., description="Number of successful logins")
    failed_logins: int = Field(..., description="Number of failed logins")

    class Config:
        json_schema_extra = {
            "example": {
                "total_logins": 15,
                "last_login": "2023-12-01T10:30:00Z",
                "successful_logins": 12,
                "failed_logins": 3
            }
        }

class UserLoginHistoryResponse(BaseModel):
    """Complete user login history with statistics"""
    user_id: int = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    login_history: List[LoginHistoryResponse] = Field(..., description="Login history records")
    stats: LoginStatsResponse = Field(..., description="Login statistics")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1,
                "email": "user@example.com",
                "login_history": [
                    {
                        "id": 1,
                        "login_time": "2023-12-01T10:30:00Z",
                        "ip_address": "192.168.1.1",
                        "user_agent": "Mozilla/5.0...",
                        "login_status": "success",
                        "failure_reason": None,
                        "user_id": 1
                    }
                ],
                "stats": {
                    "total_logins": 15,
                    "last_login": "2023-12-01T10:30:00Z",
                    "successful_logins": 12,
                    "failed_logins": 3
                }
            }
        }