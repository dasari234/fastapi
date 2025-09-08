import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db_context
from schemas.users import UserCreate, UserRole, UserUpdate, User
from services.auth_service import auth_service

logger = logging.getLogger(__name__)

class UserService:
    async def create_user(self, user_data: UserCreate, db: AsyncSession = None) -> Tuple[Optional[Dict[str, Any]], int]:
        """Create a new user with standardized response"""
        async def _create_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Check if user already exists
                result = await session.execute(
                    select(User).where(User.email == user_data.email)
                )
                existing_user = result.scalar_one_or_none()
                
                if existing_user:
                    return None, status.HTTP_409_CONFLICT
                
                # Hash password
                hashed_password = auth_service.get_password_hash(user_data.password)
                
                # Create user
                user = User(
                    email=user_data.email,
                    first_name=user_data.first_name,
                    last_name=user_data.last_name,
                    password_hash=hashed_password,
                    role=user_data.role.value if hasattr(user_data.role, 'value') else user_data.role,
                    is_active=True
                )
                
                session.add(user)
                await session.commit()
                await session.refresh(user)
                
                user_response = {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "updated_at": user.updated_at.isoformat() if user.updated_at else None
                }
                
                return user_response, status.HTTP_201_CREATED
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating user {user_data.email}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _create_user(db)
        else:
            async with get_db_context() as session:
                return await _create_user(session)

    async def get_user_by_id(self, user_id: int, db: AsyncSession = None) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get user by ID with standardized response format"""
        async def _get_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return None, status.HTTP_404_NOT_FOUND
                
                user_data = {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "updated_at": user.updated_at.isoformat() if user.updated_at else None
                }
                
                return user_data, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error getting user by ID {user_id}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _get_user(db)
        else:
            async with get_db_context() as session:
                return await _get_user(session)
        
    async def get_user_by_email(self, email: str, db: AsyncSession = None) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get user by email with standardized response"""
        async def _get_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(User).where(User.email == email)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return None, status.HTTP_404_NOT_FOUND
                
                user_data = {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "password_hash": user.password_hash,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "updated_at": user.updated_at.isoformat() if user.updated_at else None
                }
                
                return user_data, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error getting user by email {email}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _get_user(db)
        else:
            async with get_db_context() as session:
                return await _get_user(session)

    async def update_user(self, user_id: int, user_data: UserUpdate, db: AsyncSession = None) -> Tuple[Optional[Dict[str, Any]], int]:
        """Update user information"""
        async def _update_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Check if user exists first
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return None, status.HTTP_404_NOT_FOUND
                
                # Prepare update data
                update_data = user_data.dict(exclude_unset=True)
                
                # Execute update
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(**update_data)
                )
                await session.commit()
                
                # Get updated user
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                updated_user = result.scalar_one_or_none()
                
                user_response = {
                    "id": updated_user.id,
                    "email": updated_user.email,
                    "first_name": updated_user.first_name,
                    "last_name": updated_user.last_name,
                    "role": updated_user.role,
                    "is_active": updated_user.is_active,
                    "created_at": updated_user.created_at.isoformat() if updated_user.created_at else None,
                    "updated_at": updated_user.updated_at.isoformat() if updated_user.updated_at else None
                }
                
                return user_response, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error updating user {user_id}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _update_user(db)
        else:
            async with get_db_context() as session:
                return await _update_user(session)
   
    async def delete_user(self, user_id: int, db: AsyncSession = None) -> Tuple[bool, int]:
        """Delete user"""
        async def _delete_user(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # Check if user exists first
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return False, status.HTTP_404_NOT_FOUND
                
                # Delete user
                await session.execute(
                    delete(User).where(User.id == user_id)
                )
                await session.commit()
                
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error deleting user {user_id}: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _delete_user(db)
        else:
            async with get_db_context() as session:
                return await _delete_user(session)

    async def list_users(
        self, 
        page: int = 1, 
        limit: int = 10,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None,
        db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """List users with pagination and filtering with standardized response"""
        async def _list_users(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                query = select(User)
                
                if role is not None:
                    query = query.where(User.role == role.value if hasattr(role, 'value') else role)
                if is_active is not None:
                    query = query.where(User.is_active == is_active)
                
                # Count total
                count_query = query.with_only_columns(func.count()).order_by(None)
                total_count_result = await session.execute(count_query)
                total_count = total_count_result.scalar() or 0
                
                # Get paginated results
                offset = (page - 1) * limit
                query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
                
                result = await session.execute(query)
                users = result.scalars().all()
                
                response_data = {
                    "users": [
                        {
                            "id": user.id,
                            "email": user.email,
                            "first_name": user.first_name,
                            "last_name": user.last_name,
                            "role": user.role,
                            "is_active": user.is_active,
                            "created_at": user.created_at.isoformat() if user.created_at else None,
                            "updated_at": user.updated_at.isoformat() if user.updated_at else None
                        } for user in users
                    ],
                    "total_count": total_count,
                    "page": page,
                    "limit": limit,
                    "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0
                }
                
                return response_data, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error listing users: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _list_users(db)
        else:
            async with get_db_context() as session:
                return await _list_users(session)
            
# Create global instance
user_service = UserService()

