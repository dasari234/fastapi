import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import get_db
from schemas.users import UserCreate
from schemas.base import StandardResponse
from schemas.auth import Token, PasswordReset, PasswordResetRequest, RefreshTokenRequest
from services.auth_service import auth_service
from services.login_history_service import login_history_service
from services.user_service import user_service

logger = logging.getLogger(__name__)
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
            # Record failed login attempt for non-existent user
            await login_history_service.create_login_record(
                db=db,
                user_id=None,
                ip_address=ip_address,
                user_agent=user_agent,
                login_status="failed",
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


@router.post("/request-password-reset", summary="Request password reset")
async def request_password_reset(request: PasswordResetRequest):
    """Request password reset (placeholder - implement email service)"""
    return {"message": "Password reset email sent (implementation required)"}


@router.post("/reset-password", summary="Reset password")
async def reset_password(reset_data: PasswordReset):
    """Reset password with token"""
    return {
        "message": "Password reset successful (implementation required)"
    } @ router.post("/reset-password", summary="Reset password")
