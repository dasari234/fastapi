import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query

from models.database import get_db
from models.schemas import UserResponse, UserUpdate, UserListResponse, UserRole
from services.auth_service import auth_service, TokenData
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
    response_model=UserResponse,
    summary="Get current user profile"
)
async def get_current_user_profile(
    current_user: TokenData = Depends(auth_service.get_current_user),
    conn = Depends(get_db)
):
    """Get current authenticated user's profile"""
    user = await user_service.get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.get(
    "",
    response_model=UserListResponse,
    summary="List all users (Admin only)"
)
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN))
):
    """List all users with pagination and filtering (Admin only)"""
    try:
        result = await user_service.list_users(page, limit, role, is_active)
        return UserListResponse(**result)
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch users"
        )

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user by ID (Admin only)"
)
async def get_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN))
):
    """Get user by ID (Admin only)"""
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.put(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update user (Admin only)"
)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN))
):
    """Update user information (Admin only)"""
    user = await user_service.update_user(user_id, user_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user (Admin only)"
)
async def delete_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN))
):
    """Delete user (Admin only)"""
    success = await user_service.delete_user(user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

@router.put(
    "/{user_id}/activate",
    response_model=UserResponse,
    summary="Activate user (Admin only)"
)
async def activate_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN))
):
    """Activate user account (Admin only)"""
    user = await user_service.update_user(user_id, UserUpdate(is_active=True))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.put(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate user (Admin only)"
)
async def deactivate_user(
    user_id: int,
    current_user: TokenData = Depends(require_role(UserRole.ADMIN))
):
    """Deactivate user account (Admin only)"""
    user = await user_service.update_user(user_id, UserUpdate(is_active=False))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user