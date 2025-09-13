from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt
from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from loguru import logger
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM,
                        REFRESH_TOKEN_EXPIRE_DAYS, SECRET_KEY)
from app.schemas.auth import TokenData
from app.services.redis_service import redis_service

# --- Password hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- OAuth2 scheme ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class AuthService:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> Tuple[bool, Optional[str]]:
        """Verify password with status indication"""
        try:
            is_valid = pwd_context.verify(plain_password, hashed_password)
            return is_valid, None
        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False, "Password verification error"

    @staticmethod
    def get_password_hash(password: str) -> str:
        """Get password hash with status indication"""
        try:
            hashed_password = pwd_context.hash(password)
            return hashed_password
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    @staticmethod
    def create_access_token(
        data: dict, expires_delta: Optional[timedelta] = None
    ) -> Tuple[Optional[str], int]:
        """Create access token with status codes"""
        try:
            to_encode = data.copy()
            if expires_delta:
                expire = datetime.now(timezone.utc) + expires_delta
            else:
                expire = datetime.now(timezone.utc) + timedelta(
                    minutes=ACCESS_TOKEN_EXPIRE_MINUTES
                )
            to_encode.update({"exp": expire})
            encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
            return encoded_jwt, status.HTTP_200_OK
        except jwt.PyJWTError as e:
            logger.error(f"JWT encoding error: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        except Exception as e:
            logger.error(f"Failed to create access token: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    @staticmethod
    def create_refresh_token(data: dict) -> Tuple[Optional[str], int]:
        """Create refresh token with status codes"""
        try:
            to_encode = data.copy()
            expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
            to_encode.update({"exp": expire})
            encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
            return encoded_jwt, status.HTTP_200_OK
        except jwt.PyJWTError as e:
            logger.error(f"JWT encoding error for refresh token: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        except Exception as e:
            logger.error(f"Failed to create refresh token: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    @staticmethod
    def verify_token(token: str) -> Tuple[Optional[Dict[str, Any]], int]:
        """Verify JWT token with status codes"""
        try:
            # Basic token validation
            if not token or not isinstance(token, str):
                return None, status.HTTP_401_UNAUTHORIZED
            
            # Check token structure (should have 3 parts)
            if len(token.split('.')) != 3:
                return None, status.HTTP_401_UNAUTHORIZED
            
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload, status.HTTP_200_OK
            
        except ExpiredSignatureError:
            logger.warning("Token has expired")
            return None, status.HTTP_401_UNAUTHORIZED
        except InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None, status.HTTP_401_UNAUTHORIZED
        except jwt.PyJWTError as e:
            logger.error(f"JWT decoding error: {e}")
            return None, status.HTTP_401_UNAUTHORIZED
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    async def get_current_user(self, token: str = Depends(oauth2_scheme)) -> Tuple[Optional[TokenData], int]:
        """Get current user from token - returns (user_data, status_code)"""
        try:
            # Check cache first
            cached_user = await redis_service.get_cached_token(token)
            
            if cached_user:
                logger.debug("User data retrieved from cache")
                return TokenData(**cached_user), status.HTTP_200_OK
            
            # Verify token
            payload, status_code = self.verify_token(token)
            if status_code != status.HTTP_200_OK or not payload:
                return None, status.HTTP_401_UNAUTHORIZED
            
            # Extract user data
            user_id = payload.get("user_id")
            email = payload.get("email")
            role = payload.get("role", "user")
            
            if not user_id or not email:
                return None, status.HTTP_401_UNAUTHORIZED
            
            # Create TokenData object
            user_data = TokenData(
                user_id=user_id,
                email=email,
                role=role
            )
            
            # Cache the user data
            await redis_service.cache_token(token, user_data.dict())
            
            return user_data, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting current user: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    # async def authenticate_user(
    #     self, email: str, password: str, db: AsyncSession
    # ) -> Tuple[Optional[Dict[str, Any]], int]:
    #     """Authenticate user with status codes"""
    #     try:
    #         from services.user_service import user_service

    #         # Get user by email
    #         user_data, status_code = await user_service.get_user_by_email(email, db)
            
    #         if status_code != status.HTTP_200_OK or not user_data:
    #             return None, status.HTTP_401_UNAUTHORIZED

    #         # Verify password
    #         is_valid, error = self.verify_password(password, user_data["password_hash"])
    #         if not is_valid:
    #             logger.warning(f"Invalid password for user: {email}")
    #             return None, status.HTTP_401_UNAUTHORIZED
    #         if error:
    #             logger.error(f"Password verification error for user {email}: {error}")
    #             return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    #         # Check if user is active
    #         if not user_data.get("is_active", False):
    #             logger.warning(f"Inactive user attempt: {email}")
    #             return None, status.HTTP_401_UNAUTHORIZED

    #         # Remove password hash from response
    #         user_data.pop("password_hash", None)
    #         return user_data, status.HTTP_200_OK

    #     except Exception as e:
    #         logger.error(f"Authentication error for user {email}: {e}")
    #         return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    
    async def authenticate_user(
        self, email: str, password: str, db: AsyncSession, 
        ip_address: str = None, user_agent: str = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Authenticate user with status codes and login history"""
        try:
            from app.services.user_service import user_service
            from app.services.login_history_service import create_login_record

            # Get user by email
            user_data, status_code = await user_service.get_user_by_email(email, db)
            
            if status_code != status.HTTP_200_OK or not user_data:
                # Don't create login record for non-existent users (user_id would be null)
                logger.warning(f"Login attempt for non-existent user: {email}")
                return None, status.HTTP_401_UNAUTHORIZED

            # Verify password
            is_valid, error = self.verify_password(password, user_data["password_hash"])
            if not is_valid:
                logger.warning(f"Invalid password for user: {email}")
                # Create failed login record for existing user
                await create_login_record(
                    db=db,
                    user_id=user_data["id"],
                    ip_address=ip_address,
                    user_agent=user_agent,
                    login_status="failed",
                    failure_reason="Invalid password"
                )
                return None, status.HTTP_401_UNAUTHORIZED
            
            if error:
                logger.error(f"Password verification error for user {email}: {error}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

            # Check if user is active
            if not user_data.get("is_active", False):
                logger.warning(f"Inactive user attempt: {email}")
                # Create failed login record for inactive user
                await create_login_record(
                    db=db,
                    user_id=user_data["id"],
                    ip_address=ip_address,
                    user_agent=user_agent,
                    login_status="failed",
                    failure_reason="Account deactivated"
                )
                return None, status.HTTP_401_UNAUTHORIZED

            # Create successful login record
            await create_login_record(
                db=db,
                user_id=user_data["id"],
                ip_address=ip_address,
                user_agent=user_agent,
                login_status="success"
            )

            # Remove password hash from response
            user_data.pop("password_hash", None)
            return user_data, status.HTTP_200_OK

        except Exception as e:
            logger.error(f"Authentication error for user {email}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def get_current_user_dependency(self):
        """Return a dependency function"""
        async def _get_current_user(
            token: str = Depends(oauth2_scheme)
        ) -> Tuple[Optional[TokenData], int]:
            return await self.get_current_user(token)
        return _get_current_user


# --- Create global instance ---
auth_service = AuthService()









