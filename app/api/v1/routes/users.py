from datetime import datetime
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.params import Body
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.schemas.auth import TokenData
from app.schemas.base import StandardResponse
from app.schemas.users import (
    LoginStatsResponse,
    PasswordChangeRequest,
    UserLoginHistoryResponse,
    UserRole,
    UserUpdate,
)
from app.services import (
    auth_service,
    login_history_service,
    redis_service,
    user_service,
)

router = APIRouter(tags=["Users"], prefix="/users")


@router.get(
    "/me",
    response_model=StandardResponse,
    summary="Get current user profile",
    responses={
        200: {"description": "User profile retrieved successfully"},
        401: {"description": "Unauthorized - invalid or missing token"},
        500: {"description": "Internal server error"},
    },
)
async def get_current_user_profile(
    current_user_result: Tuple[Optional[TokenData], int] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user profile"""
    try:
        # Extract TokenData from tuple
        current_user, auth_status = current_user_result

        # Check if authentication was successful
        if auth_status != status.HTTP_200_OK or not current_user:
            return StandardResponse(
                success=False,
                message="Authentication failed",
                error="Invalid or expired token",
                status_code=auth_status,
            )

        # safely access current_user.user_id
        user_id = current_user.user_id

        # Get user details from database
        user_data, user_status = await user_service.get_user_by_id(user_id, db)

        if user_status != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to retrieve user data",
                error="User not found",
                status_code=user_status,
            )

        last_login, last_login_status = await login_history_service.get_last_login_time(
            db, current_user.user_id
        )

        # Remove sensitive information
        user_data.pop("password_hash", None)

        user_data["last_login"] = last_login.isoformat() if last_login else None

        return StandardResponse(
            success=True,
            message="User profile retrieved successfully",
            data=user_data,
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Failed to retrieve user profile: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Failed to retrieve user profile",
            error=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# Define allowed sort columns
ALLOWED_SORT_COLUMNS = {
    "id",
    "email",
    "first_name",
    "last_name",
    "role",
    "is_active",
    "created_at",
    "updated_at",
}


@router.get(
    "",
    response_model=StandardResponse,
    summary="List all users (Admin only)",
    responses={
        200: {"description": "Users retrieved successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        500: {"description": "Internal server error"},
    },
)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    role: Optional[UserRole] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(
        None, description="Search in email, first name, last name, or role"
    ),
    sort_by: str = Query(
        "created_at", description=f"Sort by: {', '.join(ALLOWED_SORT_COLUMNS)}"
    ),
    sort_order: str = Query("desc", description="Sort order: 'asc' or 'desc'"),
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """List all users with pagination and filtering (Admin only)"""
    try:
        # Validate sort parameters
        if sort_by not in ALLOWED_SORT_COLUMNS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort column. Allowed values: {', '.join(ALLOWED_SORT_COLUMNS)}",
            )

        if sort_order.lower() not in ["asc", "desc"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sort order. Use 'asc' or 'desc'",
            )

        result, status_code = await user_service.list_users(
            page=page,
            limit=limit,
            role=role,
            is_active=is_active,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            db=db,
        )

        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code, detail="Failed to retrieve users"
            )

        return StandardResponse(
            success=True,
            message="Users retrieved successfully",
            data=result,
            status_code=status.HTTP_200_OK,
        )

    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code,
        )
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        return StandardResponse(
            success=False,
            message="Failed to retrieve users",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/{user_id}",
    response_model=StandardResponse,
    summary="Get user by ID (Admin only)",
    responses={
        200: {"description": "User retrieved successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Get user by ID (Admin only)"""
    try:
        user_data, status_code = await user_service.get_user_by_id(user_id, db)

        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to retrieve user",
                error="Internal server error",
                status_code=status_code,
            )

        return StandardResponse(
            success=True,
            message="User retrieved successfully",
            data=user_data,
            status_code=status.HTTP_200_OK,
        )

    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code,
        )
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to retrieve user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.put(
    "/{user_id}",
    response_model=StandardResponse,
    summary="Update user information",
    responses={
        200: {"description": "User updated successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user_result: Tuple[Optional[TokenData], int] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user information - users can update their own profile, admins can update any user"""
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

        # Check if user is trying to update their own profile or is an admin
        if current_user.user_id != user_id and current_user.role != UserRole.ADMIN:
            return StandardResponse(
                success=False,
                message="Access denied",
                error="You can only update your own profile",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        # Non-admin users cannot change their role or is_active status
        if current_user.role != UserRole.ADMIN:
            # Create a copy of the update data without restricted fields
            restricted_fields = ["role", "is_active"]
            update_data = user_data.model_dump(exclude_unset=True)

            # Check if user is trying to modify restricted fields
            for field in restricted_fields:
                if field in update_data:
                    return StandardResponse(
                        success=False,
                        message="Access denied",
                        error=f"You cannot modify the {field} field",
                        status_code=status.HTTP_403_FORBIDDEN,
                    )

        # Perform the update
        user_response, status_code = await user_service.update_user(
            user_id, user_data, db
        )

        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to update user",
                error="Internal server error",
                status_code=status_code,
            )

        # Send notification about profile update
        try:
            import asyncio

            from app.hooks.notification_hooks import notify_profile_updated

            asyncio.create_task(notify_profile_updated(user_id, user_response))
        except Exception as e:
            logger.warning(f"Failed to send profile update notification: {e}")

        return StandardResponse(
            success=True,
            message="User updated successfully",
            data=user_response,
            status_code=status.HTTP_200_OK,
        )

    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code,
        )
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to update user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.delete(
    "/{user_id}",
    response_model=StandardResponse,
    summary="Delete user (Admin only)",
    responses={
        200: {"description": "User deleted successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def delete_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Delete user (Admin only)"""
    try:
        success, status_code = await user_service.delete_user(user_id, db)

        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to delete user",
                error="Internal server error",
                status_code=status_code,
            )

        return StandardResponse(
            success=True,
            message="User deleted successfully",
            data={"deleted_user_id": user_id},
            status_code=status.HTTP_200_OK,
        )

    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code,
        )
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to delete user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.put(
    "/{user_id}/activate",
    response_model=StandardResponse,
    summary="Activate user (Admin only)",
    responses={
        200: {"description": "User activated successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def activate_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Activate user account (Admin only)"""
    try:
        user_response, status_code = await user_service.update_user(
            user_id, UserUpdate(is_active=True), db
        )

        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to activate user",
                error="Internal server error",
                status_code=status_code,
            )

        return StandardResponse(
            success=True,
            message="User activated successfully",
            data=user_response,
            status_code=status.HTTP_200_OK,
        )

    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code,
        )
    except Exception as e:
        logger.error(f"Error activating user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to activate user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.put(
    "/{user_id}/deactivate",
    response_model=StandardResponse,
    summary="Deactivate user (Admin only)",
    responses={
        200: {"description": "User deactivated successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def deactivate_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate user account (Admin only)"""
    try:
        user_response, status_code = await user_service.update_user(
            user_id, UserUpdate(is_active=False), db
        )

        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to deactivate user",
                error="Internal server error",
                status_code=status_code,
            )

        return StandardResponse(
            success=True,
            message="User deactivated successfully",
            data=user_response,
            status_code=status.HTTP_200_OK,
        )

    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code,
        )
    except Exception as e:
        logger.error(f"Error deactivating user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to deactivate user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/my-history",
    response_model=UserLoginHistoryResponse,
    summary="Get current user's login history",
    responses={
        200: {"description": "Login history retrieved successfully"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_my_login_history(
    limit: int = Query(
        10, ge=1, le=100, description="Number of history records to return"
    ),
    current_user: TokenData = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's login history and statistics"""
    try:
        # Get login history
        history, history_status = await login_history_service.get_user_login_history(
            db, current_user.user_id, limit
        )

        if history_status != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login history",
            )

        # Get login statistics
        last_login, last_login_status = await login_history_service.get_last_login_time(
            db, current_user.user_id
        )
        total_logins, total_status = await login_history_service.get_login_count(
            db, current_user.user_id
        )

        # Get failed login count
        (
            failed_logins,
            failed_status,
        ) = await login_history_service.get_failed_login_count(db, current_user.user_id)

        if any(
            status != 200 for status in [last_login_status, total_status, failed_status]
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login statistics",
            )

        successful_logins = (total_logins or 0) - (failed_logins or 0)

        return UserLoginHistoryResponse(
            user_id=current_user.user_id,
            email=current_user.email,
            login_history=history or [],
            stats=LoginStatsResponse(
                total_logins=total_logins or 0,
                last_login=last_login,
                successful_logins=successful_logins,
                failed_logins=failed_logins or 0,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting login history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve login history",
        )


@router.get(
    "/user/{user_id}",
    response_model=UserLoginHistoryResponse,
    summary="Get user login history (Admin only)",
    responses={
        200: {"description": "Login history retrieved successfully"},
        403: {"description": "Forbidden - admin access required"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_user_login_history_admin(
    user_id: int,
    limit: int = Query(
        10, ge=1, le=100, description="Number of history records to return"
    ),
    current_user: TokenData = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a user's login history (Admin only)"""
    try:
        # Only admins can access other users' history
        if current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
            )

        # Get login history
        history, history_status = await login_history_service.get_user_login_history(
            db, user_id, limit
        )

        if history_status != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login history",
            )

        # Get login statistics
        last_login, last_login_status = await login_history_service.get_last_login_time(
            db, user_id
        )
        total_logins, total_status = await login_history_service.get_login_count(
            db, user_id
        )
        (
            failed_logins,
            failed_status,
        ) = await login_history_service.get_failed_login_count(db, user_id)

        if any(
            status != 200 for status in [last_login_status, total_status, failed_status]
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login statistics",
            )

        successful_logins = (total_logins or 0) - (failed_logins or 0)

        # Get user email (you might need to add a user service method for this)
        from services.user_service import user_service

        user_data, user_status = await user_service.get_user_by_id(user_id, db)

        if user_status != 200:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        return UserLoginHistoryResponse(
            user_id=user_id,
            email=user_data["email"],
            login_history=history or [],
            stats=LoginStatsResponse(
                total_logins=total_logins or 0,
                last_login=last_login,
                successful_logins=successful_logins,
                failed_logins=failed_logins or 0,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user login history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve login history",
        )
        
        
@router.post(
    "/change-password",
    response_model=StandardResponse,
    summary="Change user password",
    responses={
        200: {"description": "Password changed successfully"},
        400: {"description": "Invalid password format or passwords don't match"},
        401: {"description": "Invalid current password"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def change_password(
    password_data: PasswordChangeRequest,
    current_user_result: Tuple[Optional[TokenData], int] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change current user's password"""
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

        # Change password
        success, status_code = await user_service.change_password(
            current_user.user_id,
            password_data.current_password,
            password_data.new_password,
            db
        )

        if status_code == status.HTTP_401_UNAUTHORIZED:
            return StandardResponse(
                success=False,
                message="Password change failed",
                error="Current password is incorrect",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="Password change failed",
                error="User not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Password change failed",
                error="Internal server error",
                status_code=status_code,
            )

        # Send password change notification
        try:
            import asyncio

            from app.hooks.notification_hooks import notify_password_changed
            
            user_data, _ = await user_service.get_user_by_id(current_user.user_id, db)
            if user_data:
                asyncio.create_task(notify_password_changed(current_user.user_id, user_data))
        except Exception as e:
            logger.warning(f"Failed to send password change notification: {e}")

        return StandardResponse(
            success=True,
            message="Password changed successfully",
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Password change failed: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Password change failed",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        
        
@router.post(
    "/{user_id}/change-password-admin",
    response_model=StandardResponse,
    summary="Change user password (Admin only)",
    responses={
        200: {"description": "Password changed successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"},
    },
)
async def change_password_admin(
    user_id: int,
    new_password: str = Body(..., min_length=8, description="New password"),
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Change user password (Admin only) - bypasses current password verification"""
    try:
        # Hash new password
        new_hashed_password = auth_service.get_password_hash(new_password)
        
        # Update password directly
        result = await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                password_hash=new_hashed_password, 
                updated_at=datetime.isoformat()
            )
        )
        
        if result.rowcount == 0:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        
        await db.commit()
        
        # Invalidate cache
        await redis_service.invalidate_user(user_id)
        
        # Get user email for email cache invalidation
        user_email_result = await db.execute(
            select(User.email).where(User.id == user_id)
        )
        user_email = user_email_result.scalar_one_or_none()
        if user_email:
            await redis_service.invalidate_user_by_email(user_email)
        
        # Send forced password change notification
        try:
            import asyncio

            from app.hooks.notification_hooks import notify_password_changed_admin
            
            user_data, _ = await user_service.get_user_by_id(user_id, db)
            if user_data:
                asyncio.create_task(notify_password_changed_admin(user_id, user_data))
        except Exception as e:
            logger.warning(f"Failed to send admin password change notification: {e}")

        return StandardResponse(
            success=True,
            message="Password changed successfully",
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Admin password change failed for user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Password change failed",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
