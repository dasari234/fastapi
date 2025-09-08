from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from .users import UserRole


class Token(BaseModel):
    """Authentication tokens"""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(..., description="Token type (usually 'bearer')")
    refresh_token: str = Field(..., description="JWT refresh token")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            }
        }


class TokenData(BaseModel):
    """Token payload data"""

    user_id: int = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    role: UserRole = Field(..., description="User role")


class UserLogin(BaseModel):
    """User login credentials"""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    class Config:
        json_schema_extra = {
            "example": {"email": "user@example.com", "password": "SecurePassword123!"}
        }


class PasswordResetRequest(BaseModel):
    """Password reset request"""

    email: EmailStr = Field(..., description="User email address")

    class Config:
        json_schema_extra = {"example": {"email": "user@example.com"}}


class PasswordReset(BaseModel):
    """Password reset with token"""

    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., description="New password")

    class Config:
        json_schema_extra = {
            "example": {
                "token": "reset_token_123",
                "new_password": "NewSecurePassword123!",
            }
        }


class RefreshTokenRequest(BaseModel):
    """Refresh token request"""

    refresh_token: str = Field(..., description="Refresh token")

    class Config:
        json_schema_extra = {
            "example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
        }


class TokenWithLoginInfo(BaseModel):
    """Token response with login information"""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(..., description="Token type")
    refresh_token: str = Field(..., description="JWT refresh token")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "last_login": "2023-12-01T10:30:00Z",
            }
        }
