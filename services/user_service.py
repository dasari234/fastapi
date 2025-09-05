import logging
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Depends

from models.database_models import User, UserRole
from services.auth_service import AuthService
from models.database import get_db

logger = logging.getLogger(__name__)

class UserService:
    async def create_user(self, user_data, db: AsyncSession) -> Dict[str, Any]:
        # Check if user already exists
        result = await db.execute(
            select(User).where(User.email == user_data.email)
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists"
            )
        
        # Hash password
        hashed_password = AuthService.get_password_hash(user_data.password)
        
        # Create user
        user = User(
            email=user_data.email,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            password_hash=hashed_password,
            role=user_data.role,
            is_active=True
        )
        
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        return {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }

    async def get_user_by_id(self, user_id: int, db: AsyncSession) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            return {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
        return None

    async def get_user_by_email(self, email: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            return {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "password_hash": user.password_hash,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
        return None

    async def update_user(self, user_id: int, user_data, db: AsyncSession) -> Optional[Dict[str, Any]]:
        # First get the user
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        
        # Update fields
        update_data = {}
        if user_data.first_name is not None:
            update_data["first_name"] = user_data.first_name
        if user_data.last_name is not None:
            update_data["last_name"] = user_data.last_name
        if user_data.role is not None:
            update_data["role"] = user_data.role
        if user_data.is_active is not None:
            update_data["is_active"] = user_data.is_active
        
        if update_data:
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(**update_data)
            )
            await db.commit()
            await db.refresh(user)
        
        return {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }

    async def delete_user(self, user_id: int, db: AsyncSession) -> bool:
        result = await db.execute(
            delete(User).where(User.id == user_id)
        )
        await db.commit()
        
        return result.rowcount > 0

    async def list_users(
        self, 
        page: int = 1, 
        limit: int = 10,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        query = select(User)
        
        if role is not None:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        # Count total
        count_query = query.with_only_columns(func.count()).order_by(None)
        total_count_result = await db.execute(count_query)
        total_count = total_count_result.scalar()
        
        # Get paginated results
        offset = (page - 1) * limit
        query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        users = result.scalars().all()
        
        return {
            "users": [
                {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at
                } for user in users
            ],
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0
        }

# Create global instance
user_service = UserService()