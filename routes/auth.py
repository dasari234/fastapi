import logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from models.database import get_db
from models.schemas import UserCreate, Token, UserResponse, PasswordResetRequest, PasswordReset
from services.auth_service import auth_service
from services.user_service import user_service
from config import ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Authentication"], prefix="/auth")

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user"
)
async def register(user_data: UserCreate, conn = Depends(get_db)):
    """Register a new user"""
    try:
        user = await user_service.create_user(user_data)
        
        # Also store in file_uploads table for compatibility
        await conn.execute(
            """
            INSERT INTO file_uploads (
                original_filename, s3_key, s3_url, file_size, content_type,
                user_id, upload_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            f"user_{user['id']}",
            f"users/{user['id']}",
            f"/api/v1/users/{user['id']}",
            0,
            "application/json",
            str(user['id']),
            "success"
        )
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User registration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user"
        )

@router.post(
    "/login",
    response_model=Token,
    summary="User login"
)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), conn = Depends(get_db)):
    """Authenticate user and return tokens"""
    try:
        user = await user_service.get_user_by_email(form_data.username)
        
        if not user or not auth_service.verify_password(form_data.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Create tokens
        access_token = auth_service.create_access_token(
            data={"user_id": user["id"], "email": user["email"], "role": user["role"]}
        )
        
        refresh_token = auth_service.create_refresh_token(
            data={"user_id": user["id"], "email": user["email"]}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "refresh_token": refresh_token
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )

@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token"
)
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token"""
    try:
        payload = auth_service.verify_token(refresh_token)
        user_id = payload.get("user_id")
        email = payload.get("email")
        
        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Create new access token
        access_token = auth_service.create_access_token(
            data={"user_id": user_id, "email": email, "role": payload.get("role", "user")}
        )
        
        # Create new refresh token
        new_refresh_token = auth_service.create_refresh_token(
            data={"user_id": user_id, "email": email}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "refresh_token": new_refresh_token
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

@router.post(
    "/request-password-reset",
    summary="Request password reset"
)
async def request_password_reset(request: PasswordResetRequest):
    """Request password reset (placeholder - implement email service)"""
    return {"message": "Password reset email sent (implementation required)"}

@router.post(
    "/reset-password",
    summary="Reset password"
)
async def reset_password(reset_data: PasswordReset):
    """Reset password with token"""
    return {"message": "Password reset successful (implementation required)"}