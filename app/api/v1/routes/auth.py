from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db_session
from app.database import get_db
from app.schemas.auth import PasswordResetRequest, RefreshTokenRequest, Token, TokenData
from app.schemas.base import StandardResponse
from app.schemas.users import PasswordResetVerify, UserCreate
from app.services.auth_service import auth_service
from app.services.login_history_service import login_history_service
from app.services.password_reset_service import password_reset_service
from app.services.user_service import user_service

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
        user_data, status_code = await user_service.get_user_by_email(
            form_data.username, db
        )

        # Get client info for logging
        ip_address = request.client.host if request and request.client else None
        user_agent = request.headers.get("user-agent") if request else None
        
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create access token",
            )

        refresh_token_result, refresh_status = auth_service.create_refresh_token(
            data={"user_id": user_data["id"], "email": user_data["email"]}
        )

        if refresh_status != status.HTTP_200_OK or not refresh_token_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create refresh token",
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


@router.post("/refresh", response_model=Token, summary="Refresh access token")
async def refresh_token(
    request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token"""
    try:
        # Verify token returns a tuple (payload, status_code)
        payload, status_code = auth_service.verify_token(request.refresh_token)

        # Check if token verification was successful
        if status_code != status.HTTP_200_OK or not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
            )

        # Now extract data from the payload
        user_id = payload.get("user_id")
        email = payload.get("email")
        user_role = payload.get("role", "user")

        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token payload",
            )

        # Create new access token (returns tuple: (token, status_code))
        access_token_result, access_status = auth_service.create_access_token(
            data={"user_id": user_id, "email": email, "role": user_role}
        )

        if access_status != status.HTTP_200_OK or not access_token_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create access token",
            )

        # Create new refresh token (returns tuple: (token, status_code))
        refresh_token_result, refresh_status = auth_service.create_refresh_token(
            data={"user_id": user_id, "email": email}
        )

        if refresh_status != status.HTTP_200_OK or not refresh_token_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create refresh token",
            )

        # Return just the token strings
        return {
            "access_token": access_token_result,
            "token_type": "bearer",
            "refresh_token": refresh_token_result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
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
    current_user: Tuple[Optional[TokenData], int] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Logout user by invalidating the token and recording logout activity
    """
    try:
        
        current_user, status_code = current_user

        if not current_user or status_code != status.HTTP_200_OK:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    
        # Invalidate the token (add to blacklist)
        await auth_service.invalidate_token(
            current_user.token, db
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed due to server error"
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
        
        


    
    