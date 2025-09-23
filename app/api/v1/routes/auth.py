# [file name]: app/api/v1/routes/auth.py
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db_session
from app.database import get_db
from app.schemas.auth import PasswordResetRequest, RefreshTokenRequest, TokenData
from app.schemas.base import StandardResponse
from app.schemas.users import PasswordResetVerify, UserCreate
from app.services import (
    auth_service,
    login_history_service,
    password_reset_service,
    user_service,
)

router = APIRouter(tags=["Authentication"], prefix="/auth")

@router.post(
    "/register",
    response_model=StandardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    responses={
        201: {"description": "User created successfully"},
        409: {"description": "User with email already exists"},
        500: {"description": "Internal server error"},
    },
)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user"""
    try:
        user_response, status_code = await user_service.create_user(user_data, db)

        if status_code == status.HTTP_409_CONFLICT:
            return StandardResponse(
                success=False,
                message="Registration failed",
                error="User with this email already exists",
                status_code=status.HTTP_409_CONFLICT,
            )

        if status_code != status.HTTP_201_CREATED:
            return StandardResponse(
                success=False,
                message="Registration failed",
                error="Internal server error",
                status_code=status_code,
            )

        return StandardResponse(
            success=True,
            message="User registered successfully",
            data=user_response,
            status_code=status.HTTP_201_CREATED,
        )

    except Exception as e:
        logger.error(f"User registration failed: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Registration failed",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/login", response_model=StandardResponse, summary="User login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Authenticate user and return tokens"""
    try:
        # Get client info for logging
        ip_address = request.client.host if request and request.client else None
        user_agent = request.headers.get("user-agent") if request else None
        
        # Get user by email - returns tuple (user_data, status_code)
        user_data, status_code = await user_service.get_user_by_email(
            form_data.username, db
        )

        if status_code == status.HTTP_404_NOT_FOUND:
            # Use the new method for failed attempts without user_id
            await login_history_service.create_failed_login_attempt(
                db=db,
                email=form_data.username,
                ip_address=ip_address,
                user_agent=user_agent,
                failure_reason="User not found",
            )
            return StandardResponse(
                success=False,
                message="Login failed",
                error="Invalid credentials",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Login failed",
                error="Internal server error",
                status_code=status_code,
            )

        # Verify password
        is_valid, error = auth_service.verify_password(
            form_data.password, user_data["password_hash"]
        )

        if not is_valid:
            # Record failed login attempt
            await login_history_service.create_login_record(
                db=db,
                user_id=user_data["id"],
                ip_address=ip_address,
                user_agent=user_agent,
                login_status="failed",
                failure_reason="Invalid password",
            )
            return StandardResponse(
                success=False,
                message="Login failed",
                error="Invalid credentials",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if not user_data["is_active"]:
            # Record failed login attempt for inactive account
            await login_history_service.create_login_record(
                db=db,
                user_id=user_data["id"],
                ip_address=ip_address,
                user_agent=user_agent,
                login_status="failed",
                failure_reason="Account deactivated",
            )
            return StandardResponse(
                success=False,
                message="Login failed",
                error="User account is deactivated",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Record successful login
        await login_history_service.create_login_record(
            db=db,
            user_id=user_data["id"],
            ip_address=ip_address,
            user_agent=user_agent,
            login_status="success",
        )

        # Get the previous last login time BEFORE the current login is recorded
        previous_last_login, _ = await login_history_service.get_last_login_time(
            db, user_data["id"]
        )

        # Create tokens and return response
        access_token_result, access_status = auth_service.create_access_token(
            data={
                "user_id": user_data["id"],
                "email": user_data["email"],
                "role": user_data["role"],
            }
        )

        if access_status != status.HTTP_200_OK or not access_token_result:
            return StandardResponse(
                success=False,
                message="Login failed",
                error="Failed to create access token",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        refresh_token_result, refresh_status = auth_service.create_refresh_token(
            data={"user_id": user_data["id"], "email": user_data["email"], "role": user_data["role"]}
        )

        if refresh_status != status.HTTP_200_OK or not refresh_token_result:
            return StandardResponse(
                success=False,
                message="Login failed",
                error="Failed to create refresh token",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Remove password hash from response
        user_data.pop("password_hash", None)

        user_data["last_login"] = (
            previous_last_login.isoformat() if previous_last_login else None
        )

        response_data = {
            "access_token": access_token_result,
            "token_type": "bearer",
            "refresh_token": refresh_token_result,
            "user": user_data,
        }

        return StandardResponse(
            success=True,
            message="Login successful",
            data=response_data,
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Login failed: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Login failed",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/refresh", response_model=StandardResponse, summary="Refresh access token")
async def refresh_token(
    request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token"""
    try:
        from app.services.auth_service import auth_service

        # First check if the refresh token is expired
        is_expired, payload = auth_service.is_token_expired(request.refresh_token)
        
        if is_expired:
            logger.warning("Refresh token has expired")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="Refresh token has expired",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        
        # If not expired, verify the token properly
        verified_payload, status_code = await auth_service.verify_token(request.refresh_token, db)

        # Check if token verification was successful
        if status_code != status.HTTP_200_OK or not verified_payload:
            logger.warning(f"Invalid refresh token: {status_code}")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="Invalid refresh token",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Use the payload from proper verification - PRESERVE THE ORIGINAL ROLE
        user_id = verified_payload.get("user_id")
        email = verified_payload.get("email")
        user_role = verified_payload.get("role")  # Remove default value - use whatever is in the token

        if not user_id or not email:
            logger.warning("Refresh token missing required fields")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="Invalid refresh token payload",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # If role is missing from token, get it from the database
        if not user_role:
            from app.services.user_service import user_service
            user_data, user_status = await user_service.get_user_by_id(user_id, db)
            
            if user_status == status.HTTP_200_OK and user_data:
                user_role = user_data.get("role", "user")
                logger.debug(f"Retrieved role from database: {user_role}")
            else:
                user_role = "user"  # Fallback only if we can't get from DB
                logger.warning(f"Could not retrieve user role from DB for user {user_id}, using default")
        else:
            logger.debug(f"Using role from token: {user_role}")

        # Verify user still exists and is active
        from app.services.user_service import user_service
        user_data, user_status = await user_service.get_user_by_id(user_id, db)
        
        if user_status != status.HTTP_200_OK or not user_data:
            logger.warning(f"User not found during token refresh: {user_id}")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="User not found",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if not user_data.get("is_active", False):
            logger.warning(f"Inactive user attempt during token refresh: {user_id}")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="User account is deactivated",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # DEBUG: Log the token creation with correct role
        logger.debug(f"Creating new tokens for user_id: {user_id}, role: {user_role}")

        # Create new access token with the correct role
        access_token_result, access_status = auth_service.create_access_token(
            data={"user_id": user_id, "email": email, "role": user_role}
        )

        if access_status != status.HTTP_200_OK or not access_token_result:
            logger.error("Failed to create access token during refresh")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="Failed to create access token",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Create new refresh token with the correct role
        refresh_token_result, refresh_status = auth_service.create_refresh_token(
            data={"user_id": user_id, "email": email, "role": user_role}
        )

        if refresh_status != status.HTTP_200_OK or not refresh_token_result:
            logger.error("Failed to create refresh token during refresh")
            return StandardResponse(
                success=False,
                message="Token refresh failed",
                error="Failed to create refresh token",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Return the response
        return StandardResponse(
            success=True,
            message="Token refreshed successfully",
            data={
                "access_token": access_token_result,
                "token_type": "bearer",
                "refresh_token": refresh_token_result,
            },
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Token refresh failed: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Token refresh failed",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
@router.post(
    "/logout",
    response_model=StandardResponse,
    summary="User logout",
    description="Invalidate user token and log logout activity",
    responses={
        200: {"description": "Successfully logged out"},
        401: {"description": "Invalid or expired token"},
        500: {"description": "Internal server error"},
    },
)
async def logout(
    response: Response,
    current_user_result: Tuple[Optional[TokenData], int] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Logout user by invalidating the token and recording logout activity
    """
    try:
        # Extract TokenData from tuple
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            return StandardResponse(
                success=False,
                message="Authentication failed",
                error="Invalid or expired token",
                status_code=auth_status,
            )
    
        # Invalidate the token (add to blacklist)
        success, invalidate_status = await auth_service.invalidate_token(
            current_user.token, db
        )
        
        if not success:
            return StandardResponse(
                success=False,
                message="Logout failed",
                error="Failed to invalidate token",
                status_code=invalidate_status,
            )
                
        # Record logout activity in login history
        await login_history_service.create_logout_record(
            db=db,
            user_id=current_user.user_id,
            logout_time=datetime.now(timezone.utc)
        )
        
        # Clear the authentication cookie if you're using cookies
        response.delete_cookie(key="access_token")
        
        return StandardResponse(
            success=True,
            message="Successfully logged out",
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Logout failed: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Logout failed",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@router.post(
    "/forgot-password",
    response_model=StandardResponse,
    summary="Request password reset",
    description="Send password reset email to user",
    responses={
        202: {"description": "Reset email sent if account exists"},
        500: {"description": "Internal server error"},
    },
)
async def forgot_password(
    request: PasswordResetRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Request password reset by email"""
    try:
        success, status_code = await password_reset_service.send_password_reset_email(request.email, db)
        
        if status_code == status.HTTP_200_OK:
            return StandardResponse(
                success=True,
                message="If an account with that email exists, a password reset link has been sent",
                status_code=status.HTTP_202_ACCEPTED
            )
        else:
            return StandardResponse(
                success=False,
                message="Error processing password reset request",
                status_code=status_code
            )
            
    except Exception as e:
        logger.error(f"Password reset request failed: {e}")
        return StandardResponse(
            success=False,
            message="Error processing password reset request",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        

@router.post(
    "/reset-password",
    response_model=StandardResponse,
    summary="Reset password",
    description="Reset password using valid reset token",
    responses={
        200: {"description": "Password reset successful"},
        400: {"description": "Invalid token or password"},
        404: {"description": "Token not found"},
        410: {"description": "Token expired"},
        500: {"description": "Internal server error"},
    },
)
async def reset_password(
    request: PasswordResetVerify,
    db: AsyncSession = Depends(get_db_session),
):
    """Reset password using valid reset token"""
    try:
        success, status_code = await password_reset_service.reset_password(
            request.token, request.new_password, db
        )
        
        if success:
            return StandardResponse(
                success=True,
                message="Password reset successfully",
                status_code=status.HTTP_200_OK
            )
        else:
            if status_code == status.HTTP_404_NOT_FOUND:
                message = "Invalid or expired reset token"
            elif status_code == status.HTTP_410_GONE:
                message = "Reset token has expired"
            else:
                message = "Error resetting password"
                
            return StandardResponse(
                success=False,
                message=message,
                status_code=status_code
            )
            
    except Exception as e:
        logger.error(f"Password reset failed: {e}")
        return StandardResponse(
            success=False,
            message="Error resetting password",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
@router.get(
    "/verify-reset-token/{token}",
    response_model=StandardResponse,
    summary="Verify reset token",
    description="Check if a password reset token is valid",
    responses={
        200: {"description": "Token is valid"},
        404: {"description": "Token not found"},
        410: {"description": "Token expired"},
        500: {"description": "Internal server error"},
    },
)
async def verify_reset_token(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify if a password reset token is valid"""
    try:
        email, status_code = await password_reset_service.verify_reset_token(token, db)
        
        if status_code == status.HTTP_200_OK:
            return StandardResponse(
                success=True,
                message="Token is valid",
                status_code=status.HTTP_200_OK
            )
        else:
            if status_code == status.HTTP_404_NOT_FOUND:
                message = "Invalid reset token"
            elif status_code == status.HTTP_410_GONE:
                message = "Reset token has expired"
            else:
                message = "Error verifying token"
                
            return StandardResponse(
                success=False,
                message=message,
                status_code=status_code
            )
            
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        return StandardResponse(
            success=False,
            message="Error verifying token",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )