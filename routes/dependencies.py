from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from models.schemas import UserRole
from services.auth_service import TokenData, auth_service


async def get_current_user() -> Tuple[Optional[TokenData], int]:
    """Dependency to get current user"""
    return await auth_service.get_current_user()

async def get_db_session() -> AsyncSession:
    """Dependency to get database session"""
    async with get_db() as session:
        yield session

def require_role(required_role: UserRole):
    """Role-based dependency factory"""
    async def role_checker(
        current_user_result: Tuple[Optional[TokenData], int] = Depends(get_current_user)
    ):
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        if current_user.role != required_role and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker

# Common role dependencies
require_admin = require_role(UserRole.ADMIN)
require_user = require_role(UserRole.USER)




