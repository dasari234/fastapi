from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from models.database import get_db
from models.schemas import (LoginHistory, PasswordReset, PasswordResetRequest, Token, TokenData, TokenWithLoginInfo,
                            UserCreate, UserResponse)
from services.auth_service import auth_service
from services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Authentication"], prefix="/auth")

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user"
)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user"""
    try:
        # Use the database session directly
        user = await user_service.create_user(user_data, db)
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User registration failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user"
        )

@router.post(
    "/login",
    response_model=TokenWithLoginInfo,
    summary="User login"
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: AsyncSession = Depends(get_db),
    request: Request = None
):
    """Authenticate user and return tokens"""
    try:
        user = await user_service.get_user_by_email(form_data.username, db)
        
        ip_address = request.client.host if request and request.client else None
        user_agent = request.headers.get("user-agent") if request else None
         
        if not user or not auth_service.verify_password(form_data.password, user["password_hash"]):
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not user["is_active"]:
            login_record = LoginHistory(
            user_id=user["id"],
            ip_address=ip_address,
            user_agent=user_agent,
            login_status="failed",
            failure_reason="Account deactivated"
            )
            db.add(login_record)
            await db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated",
                headers={"WWW-Authenticate": "Bearer"},
            )
            # Log failed login attempt for deactivated account
            
            
        login_record = LoginHistory(
            user_id=user["id"],
            ip_address=ip_address,
            user_agent=user_agent,
            login_status="success",
            failure_reason="Account activated"
        )
        db.add(login_record)
        await db.commit()
               
        
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
        await db.rollback()
        logger.error(f"Login failed: {e}", exc_info=True)
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

@router.get(
    "/login-history",
    summary="Get user profile with last login info"
)
async def get_user_profile(
    current_user: TokenData = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user profile including last login time"""
    from services.login_history_service import login_history_service
    
    last_login = await login_history_service.get_last_login_time(db, current_user.user_id)
    login_count = await login_history_service.get_login_count(db, current_user.user_id)
    
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "role": current_user.role,
        "last_login": last_login.isoformat() if last_login else None,
        "total_logins": login_count
    }
