import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncpg
from fastapi import HTTPException, status

from models.database import get_db, ensure_db_initialized
from models.schemas import UserCreate, UserUpdate, UserRole
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

class UserService:
    async def create_user(self, user_data: UserCreate) -> Dict[str, Any]:
        db_pool = await ensure_db_initialized()
        
        async with db_pool.acquire() as conn:
            # Check if user already exists
            existing_user = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", user_data.email
            )
            
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this email already exists"
                )
            
            # Hash password
            hashed_password = AuthService.get_password_hash(user_data.password)
            
            # Create user
            user = await conn.fetchrow(
                """
                INSERT INTO users (email, first_name, last_name, password_hash, role, is_active)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, email, first_name, last_name, role, is_active, created_at, updated_at
                """,
                user_data.email,
                user_data.first_name,
                user_data.last_name,
                hashed_password,
                user_data.role.value,
                True
            )
            
            return dict(user)

    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        db_pool = await ensure_db_initialized()
        
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow(
                """
                SELECT id, email, first_name, last_name, role, is_active, created_at, updated_at
                FROM users WHERE id = $1
                """,
                user_id
            )
            
            return dict(user) if user else None

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        db_pool = await ensure_db_initialized()
        
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow(
                """
                SELECT id, email, first_name, last_name, password_hash, role, is_active, created_at, updated_at
                FROM users WHERE email = $1
                """,
                email
            )
            
            return dict(user) if user else None

    async def update_user(self, user_id: int, user_data: UserUpdate) -> Optional[Dict[str, Any]]:
        db_pool = await ensure_db_initialized()
        
        async with db_pool.acquire() as conn:
            update_fields = []
            params = []
            param_count = 1
            
            if user_data.first_name is not None:
                update_fields.append(f"first_name = ${param_count}")
                params.append(user_data.first_name)
                param_count += 1
            
            if user_data.last_name is not None:
                update_fields.append(f"last_name = ${param_count}")
                params.append(user_data.last_name)
                param_count += 1
            
            if user_data.role is not None:
                update_fields.append(f"role = ${param_count}")
                params.append(user_data.role.value)
                param_count += 1
            
            if user_data.is_active is not None:
                update_fields.append(f"is_active = ${param_count}")
                params.append(user_data.is_active)
                param_count += 1
            
            if not update_fields:
                return None
            
            params.append(user_id)
            
            query = f"""
                UPDATE users 
                SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ${param_count}
                RETURNING id, email, first_name, last_name, role, is_active, created_at, updated_at
            """
            
            user = await conn.fetchrow(query, *params)
            return dict(user) if user else None

    async def delete_user(self, user_id: int) -> bool:
        db_pool = await ensure_db_initialized()
        
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM users WHERE id = $1",
                user_id
            )
            
            return result == "DELETE 1"

    async def list_users(
        self, 
        page: int = 1, 
        limit: int = 10,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None
    ) -> Dict[str, Any]:
        db_pool = await ensure_db_initialized()
        
        async with db_pool.acquire() as conn:
            conditions = []
            params = []
            param_count = 1
            
            if role is not None:
                conditions.append(f"role = ${param_count}")
                params.append(role.value)
                param_count += 1
            
            if is_active is not None:
                conditions.append(f"is_active = ${param_count}")
                params.append(is_active)
                param_count += 1
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # Count total
            count_query = f"SELECT COUNT(*) FROM users WHERE {where_clause}"
            total_count = await conn.fetchval(count_query, *params)
            
            # Get paginated results
            offset = (page - 1) * limit
            params.extend([limit, offset])
            
            data_query = f"""
                SELECT id, email, first_name, last_name, role, is_active, created_at, updated_at
                FROM users WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_count} OFFSET ${param_count + 1}
            """
            
            users = await conn.fetch(data_query, *params)
            
            return {
                "users": [dict(user) for user in users],
                "total_count": total_count,
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit
            }

# Create global instance
user_service = UserService()