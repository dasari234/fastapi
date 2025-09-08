# routes/users.py
import logging
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from models.schemas import (LoginStatsResponse, StandardResponse,
                            UserLoginHistoryResponse, UserRole, UserUpdate)
from services import login_history_service
from services.auth_service import TokenData, auth_service
from services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Users"], prefix="/users")

# Role-based dependency
def require_role(required_role: UserRole):
    async def role_checker(current_user: TokenData = Depends(auth_service.get_current_user)):
        if current_user.role != required_role and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker

@router.get(
    "/me",
    response_model=StandardResponse,
    summary="Get current user profile",
    responses={
        200: {"description": "User profile retrieved successfully"},
        401: {"description": "Unauthorized - invalid or missing token"},
        500: {"description": "Internal server error"}
    }
)
async def get_current_user_profile(
    current_user_result: Tuple[Optional[TokenData], int] = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
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
                status_code=auth_status
            )
        
        # Now you can safely access current_user.user_id
        user_id = current_user.user_id
        
        # Get user details from database
        user_data, user_status = await user_service.get_user_by_id(user_id, db)
        
        if user_status != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to retrieve user data",
                error="User not found",
                status_code=user_status
            )
        
        # Remove sensitive information
        user_data.pop("password_hash", None)
        
        return StandardResponse(
            success=True,
            message="User profile retrieved successfully",
            data=user_data,
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to retrieve user profile: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Failed to retrieve user profile",
            error=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.get(
    "",
    response_model=StandardResponse,
    summary="List all users (Admin only)",
    responses={
        200: {"description": "Users retrieved successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        500: {"description": "Internal server error"}
    }
)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    role: Optional[UserRole] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """List all users with pagination and filtering (Admin only)"""
    try:
        result = await user_service.list_users(page, limit, role, is_active, db)
        
        return StandardResponse(
            success=True,
            message="Users retrieved successfully",
            data=result,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code
        )
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        return StandardResponse(
            success=False,
            message="Failed to retrieve users",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.get(
    "/{user_id}",
    response_model=StandardResponse,
    summary="Get user by ID (Admin only)",
    responses={
        200: {"description": "User retrieved successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID (Admin only)"""
    try:
        user_data, status_code = await user_service.get_user_by_id(user_id, db)
        
        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to retrieve user",
                error="Internal server error",
                status_code=status_code
            )
        
        return StandardResponse(
            success=True,
            message="User retrieved successfully",
            data=user_data,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code
        )
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to retrieve user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.put(
    "/{user_id}",
    response_model=StandardResponse,
    summary="Update user (Admin only)",
    responses={
        200: {"description": "User updated successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Update user information (Admin only)"""
    try:
        user_response, status_code = await user_service.update_user(user_id, user_data, db)
        
        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to update user",
                error="Internal server error",
                status_code=status_code
            )
        
        return StandardResponse(
            success=True,
            message="User updated successfully",
            data=user_response,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code
        )
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to update user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.delete(
    "/{user_id}",
    response_model=StandardResponse,
    summary="Delete user (Admin only)",
    responses={
        200: {"description": "User deleted successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Delete user (Admin only)"""
    try:
        success, status_code = await user_service.delete_user(user_id, db)
        
        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to delete user",
                error="Internal server error",
                status_code=status_code
            )
        
        return StandardResponse(
            success=True,
            message="User deleted successfully",
            data={"deleted_user_id": user_id},
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code
        )
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to delete user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.put(
    "/{user_id}/activate",
    response_model=StandardResponse,
    summary="Activate user (Admin only)",
    responses={
        200: {"description": "User activated successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def activate_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Activate user account (Admin only)"""
    try:
        user_response, status_code = await user_service.update_user(
            user_id, 
            UserUpdate(is_active=True), 
            db
        )
        
        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to activate user",
                error="Internal server error",
                status_code=status_code
            )
        
        return StandardResponse(
            success=True,
            message="User activated successfully",
            data=user_response,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code
        )
    except Exception as e:
        logger.error(f"Error activating user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to activate user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.put(
    "/{user_id}/deactivate",
    response_model=StandardResponse,
    summary="Deactivate user (Admin only)",
    responses={
        200: {"description": "User deactivated successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def deactivate_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate user account (Admin only)"""
    try:
        user_response, status_code = await user_service.update_user(
            user_id, 
            UserUpdate(is_active=False), 
            db
        )
        
        if status_code == status.HTTP_404_NOT_FOUND:
            return StandardResponse(
                success=False,
                message="User not found",
                error=f"User with ID {user_id} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to deactivate user",
                error="Internal server error",
                status_code=status_code
            )
        
        return StandardResponse(
            success=True,
            message="User deactivated successfully",
            data=user_response,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException as he:
        return StandardResponse(
            success=False,
            message="Access denied",
            error=he.detail,
            status_code=he.status_code
        )
    except Exception as e:
        logger.error(f"Error deactivating user {user_id}: {e}")
        return StandardResponse(
            success=False,
            message="Failed to deactivate user",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        

@router.get(
    "/my-history",
    response_model=UserLoginHistoryResponse,
    summary="Get current user's login history",
    responses={
        200: {"description": "Login history retrieved successfully"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"}
    }
)
async def get_my_login_history(
    limit: int = Query(10, ge=1, le=100, description="Number of history records to return"),
    current_user: TokenData = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
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
                detail="Failed to retrieve login history"
            )
        
        # Get login statistics
        last_login, last_login_status = await login_history_service.get_last_login_time(db, current_user.user_id)
        total_logins, total_status = await login_history_service.get_login_count(db, current_user.user_id)
        
        # Get failed login count
        failed_logins, failed_status = await login_history_service.get_failed_login_count(db, current_user.user_id)
        
        if any(status != 200 for status in [last_login_status, total_status, failed_status]):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login statistics"
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
                failed_logins=failed_logins or 0
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting login history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve login history"
        )

@router.get(
    "/user/{user_id}",
    response_model=UserLoginHistoryResponse,
    summary="Get user login history (Admin only)",
    responses={
        200: {"description": "Login history retrieved successfully"},
        403: {"description": "Forbidden - admin access required"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_user_login_history_admin(
    user_id: int,
    limit: int = Query(10, ge=1, le=100, description="Number of history records to return"),
    current_user: TokenData = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a user's login history (Admin only)"""
    try:
        # Only admins can access other users' history
        if current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        # Get login history
        history, history_status = await login_history_service.get_user_login_history(db, user_id, limit)
        
        if history_status != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login history"
            )
        
        # Get login statistics
        last_login, last_login_status = await login_history_service.get_last_login_time(db, user_id)
        total_logins, total_status = await login_history_service.get_login_count(db, user_id)
        failed_logins, failed_status = await login_history_service.get_failed_login_count(db, user_id)
        
        if any(status != 200 for status in [last_login_status, total_status, failed_status]):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve login statistics"
            )
        
        successful_logins = (total_logins or 0) - (failed_logins or 0)
        
        # Get user email (you might need to add a user service method for this)
        from services.user_service import user_service
        user_data, user_status = await user_service.get_user_by_id(user_id, db)
        
        if user_status != 200:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserLoginHistoryResponse(
            user_id=user_id,
            email=user_data["email"],
            login_history=history or [],
            stats=LoginStatsResponse(
                total_logins=total_logins or 0,
                last_login=last_login,
                successful_logins=successful_logins,
                failed_logins=failed_logins or 0
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user login history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve login history"
        )


