from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import status
from loguru import logger
from sqlalchemy import String, asc, delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import CACHE_TTL_USER
from app.database import get_db_context
from app.hooks.notification_hooks import notify_user_created
from app.models.file_history import FileHistory
from app.models.files import FileUploadRecord
from app.models.login_history import LoginHistory
from app.models.user import PasswordResetToken, TokenBlacklist, User
from app.redis.redis_utils import (is_redis_available, safe_redis_get,
                                   safe_redis_set)
from app.schemas.users import UserCreate, UserRole, UserUpdate
from app.services import auth_service, redis_service


class UserService:
    async def create_user(
        self, user_data: UserCreate, db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Create a new user with standardized response"""

        async def _create_user(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
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
                    role=user_data.role.value
                    if hasattr(user_data.role, "value")
                    else user_data.role,
                    is_active=True,
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
                    "created_at": user.created_at.isoformat()
                    if user.created_at
                    else None,
                    "updated_at": user.updated_at.isoformat()
                    if user.updated_at
                    else None,
                }

                # Cache the new user if Redis is available
                if is_redis_available():
                    await safe_redis_set(f"user:{user.id}", user_response, CACHE_TTL_USER)
                    await safe_redis_set(f"user_email:{user.email}", user_response, CACHE_TTL_USER)
                
                # Send notification
                if user_response:                    
                    import asyncio
                    asyncio.create_task(notify_user_created(user.id, user_response))

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
            
    async def get_user_by_id(
        self, user_id: int, db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get user by ID with Redis caching and database fallback"""
        # Check Redis cache first if available
        if is_redis_available():
            cached_user = await safe_redis_get(f"user:{user_id}")
            if cached_user:
                logger.debug(f"User {user_id} retrieved from Redis cache")
                return cached_user, status.HTTP_200_OK

        # If Redis not available or cache miss, get from database
        async def _get_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(
                        User.id,
                        User.email,
                        User.first_name,
                        User.last_name,
                        User.password_hash,
                        User.role,
                        User.is_active,
                        User.created_at,
                        User.updated_at
                    ).where(User.id == user_id)
                )
                user = result.first()
                
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
                    "updated_at": user.updated_at.isoformat() if user.updated_at else None,
                }

                # Cache the user data if Redis is available
                if is_redis_available():
                    await safe_redis_set(f"user:{user_id}", user_data, CACHE_TTL_USER)

                return user_data, status.HTTP_200_OK

            except Exception as e:
                logger.error(f"Error getting user by ID {user_id}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _get_user(db)
        else:
            async with get_db_context() as session:
                return await _get_user(session)

    async def get_user_by_email(
        self, email: str, db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get user by email with Redis caching and database fallback"""
        # Check Redis cache first if available
        if is_redis_available():
            cached_user = await safe_redis_get(f"user_email:{email}")
            if cached_user:
                logger.debug(f"User {email} retrieved from Redis cache")
                return cached_user, status.HTTP_200_OK

        # If Redis not available or cache miss, get from database
        async def _get_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(select(User).where(User.email == email))
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
                    "updated_at": user.updated_at.isoformat() if user.updated_at else None,
                }
                
                # Cache the user data if Redis is available
                if is_redis_available():
                    await safe_redis_set(f"user:{user.id}", user_data, CACHE_TTL_USER)
                    await safe_redis_set(f"user_email:{user.email}", user_data, CACHE_TTL_USER)

                return user_data, status.HTTP_200_OK

            except Exception as e:
                logger.error(f"Error getting user by email {email}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _get_user(db)
        else:
            async with get_db_context() as session:
                return await _get_user(session)

    async def update_user(
        self, user_id: int, user_data: UserUpdate, db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Update user information and clear cache"""
        async def _update_user(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Check if user exists first
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()

                if not user:
                    return None, status.HTTP_404_NOT_FOUND

                # Get current email for cache invalidation
                old_email = user.email

                # Prepare update data
                update_data = user_data.model_dump(exclude_unset=True)

                # Execute update
                await session.execute(
                    update(User).where(User.id == user_id).values(**update_data)
                )
                await session.commit()

                # Get updated user
                result = await session.execute(select(User).where(User.id == user_id))
                updated_user = result.scalar_one_or_none()

                user_response = {
                    "id": updated_user.id,
                    "email": updated_user.email,
                    "first_name": updated_user.first_name,
                    "last_name": updated_user.last_name,
                    "role": updated_user.role,
                    "is_active": updated_user.is_active,
                    "created_at": updated_user.created_at.isoformat()
                    if updated_user.created_at
                    else None,
                    "updated_at": updated_user.updated_at.isoformat()
                    if updated_user.updated_at
                    else None,
                }

                # Invalidate cache for both old and new email if email changed
                if is_redis_available():
                    await redis_service.invalidate_user(user_id)
                    await redis_service.invalidate_user_by_email(old_email)

                    if "email" in update_data and update_data["email"] != old_email:
                        await redis_service.invalidate_user_by_email(update_data["email"])

                # Cache the updated user if Redis is available
                if is_redis_available():
                    await safe_redis_set(f"user:{user_id}", user_response, CACHE_TTL_USER)
                    await safe_redis_set(f"user_email:{updated_user.email}", user_response, CACHE_TTL_USER)

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
    
    async def delete_user(
        self, user_id: int, db: AsyncSession = None
    ) -> Tuple[bool, int]:
        """Delete user"""

        async def _delete_user(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # Check if user exists first
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()

                if not user:
                    return False, status.HTTP_404_NOT_FOUND

                # 1. Delete login history
                await session.execute(
                    delete(LoginHistory).where(LoginHistory.user_id == user_id)
                )
                logger.info(f"Deleted login history for user {user_id}")

                # 2. Delete file actions history
                await session.execute(
                    delete(FileHistory).where(FileHistory.action_by == user_id)
                )
                logger.info(f"Deleted file actions history for user {user_id}")

                # 3. File uploads
                await session.execute(
                    delete(FileUploadRecord).where(FileUploadRecord.user_id == user_id)
                )
                logger.info(f"Deleted file uploads for user {user_id}")
                
                # 4. Delete password reset tokens
                await session.execute(
                    delete(PasswordResetToken).where(PasswordResetToken.email == user.email)
                )
                logger.info(f"Deleted password reset tokens for user {user_id}")
                
                # 5. Delete token blacklist entries (if applicable)
                await session.execute(
                    delete(TokenBlacklist).where(TokenBlacklist.token.contains(f"user_id:{user_id}")) 
                )

                # Get email for cache invalidation
                user_email = user.email

                # Delete user
                await session.delete(user)
                await session.commit()

                # Invalidate cache if Redis is available
                if is_redis_available():
                    await redis_service.invalidate_user(user_id)
                    await redis_service.invalidate_user_by_email(user_email)
                
                logger.info(f"Successfully deleted user {user_id}")
                
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
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """List users with pagination and filtering with standardized response"""

        async def _list_users(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                query = select(User)

                if role is not None:
                    query = query.where(
                        User.role == role.value if hasattr(role, "value") else role
                    )
                if is_active is not None:
                    query = query.where(User.is_active == is_active)

                # Apply search
                if search:
                    search_filter = or_(
                        User.email.ilike(f"%{search}%"),
                        User.first_name.ilike(f"%{search}%"),
                        User.last_name.ilike(f"%{search}%"),
                        User.role.ilike(f"%{search}%")
                        if isinstance(User.role.type, String)
                        else None,
                    )
                    query = query.where(search_filter)

                # Count total
                count_query = query.with_only_columns(func.count()).order_by(None)
                total_count_result = await session.execute(count_query)
                total_count = total_count_result.scalar() or 0

                # Apply sorting
                sort_column = getattr(User, sort_by, User.created_at)
                if sort_order.lower() == "asc":
                    query = query.order_by(asc(sort_column))
                else:
                    query = query.order_by(desc(sort_column))

                # Get paginated results
                offset = (page - 1) * limit
                query = query.offset(offset).limit(limit)

                result = await session.execute(query)
                users = result.scalars().all()

                users_data = []
                for user in users:
                    user_data = {
                        "id": user.id,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "role": user.role,
                        "is_active": user.is_active,
                        "created_at": user.created_at.isoformat()
                        if user.created_at
                        else None,
                        "updated_at": user.updated_at.isoformat()
                        if user.updated_at
                        else None,
                    }
                    users_data.append(user_data)

                    # Cache individual users for faster single lookups if Redis is available
                    if is_redis_available():
                        await safe_redis_set(f"user:{user.id}", user_data, CACHE_TTL_USER)
                        await safe_redis_set(f"user_email:{user.email}", user_data, CACHE_TTL_USER)

                response_data = {
                    "users": users_data,
                    "total_count": total_count,
                    "page": page,
                    "limit": limit,
                    "total_pages": (total_count + limit - 1) // limit
                    if limit > 0
                    else 0,
                    "has_next": page * limit < total_count,
                    "has_prev": page > 1,
                    "filters": {"role": role, "is_active": is_active, "search": search},
                    "sorting": {"sort_by": sort_by, "sort_order": sort_order},
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
            
    async def change_password(
        self, 
        user_id: int, 
        current_password: str, 
        new_password: str,
        db: AsyncSession = None
    ) -> Tuple[bool, int]:
        """Change user password with verification"""
        
        async def _change_password(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # Get user with password hash
                result = await session.execute(
                    select(User.id, User.password_hash).where(User.id == user_id)
                )
                user = result.first()
                
                if not user:
                    return False, status.HTTP_404_NOT_FOUND
                
                # Verify current password
                is_valid, error = auth_service.verify_password(current_password, user.password_hash)
                
                if not is_valid:
                    logger.warning(f"Invalid current password for user {user_id}")
                    return False, status.HTTP_401_UNAUTHORIZED
                
                if error:
                    logger.error(f"Password verification error for user {user_id}: {error}")
                    return False, status.HTTP_500_INTERNAL_SERVER_ERROR
                
                # Hash new password
                new_hashed_password = auth_service.get_password_hash(new_password)
                
                # Update password
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(password_hash=new_hashed_password, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()
                
                # Invalidate user cache if Redis is available
                if is_redis_available():
                    await redis_service.invalidate_user(user_id)
                
                # Get user email for email cache invalidation
                user_email_result = await session.execute(
                    select(User.email).where(User.id == user_id)
                )
                user_email = user_email_result.scalar_one_or_none()
                if user_email and is_redis_available():
                    await redis_service.invalidate_user_by_email(user_email)
                
                logger.info(f"Password changed successfully for user {user_id}")
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error changing password for user {user_id}: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _change_password(db)
        else:
            async with get_db_context() as session:
                return await _change_password(session)


# Create global instance
user_service = UserService()