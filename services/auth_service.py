import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import (ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM,
                    REFRESH_TOKEN_EXPIRE_DAYS, SECRET_KEY)
from models.database import get_db
from models.schemas import TokenData, User, UserRole

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
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
            print(f"Generated hash: {hashed_password}")
            print(f"Hash type: {type(hashed_password)}")
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

    @staticmethod
    async def get_current_user(
        token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
    ) -> Tuple[Optional[TokenData], int]:
        """Get current user with status codes"""
        try:
            # Verify token
            payload, status_code = AuthService.verify_token(token)
            if status_code != status.HTTP_200_OK or not payload:
                return None, status_code

            user_id: int = payload.get("user_id")
            email: str = payload.get("email")
            role: str = payload.get("role")

            # Validate token payload
            if user_id is None or email is None or role is None:
                logger.warning("Invalid token payload: missing required fields")
                return None, status.HTTP_401_UNAUTHORIZED

            # Verify user exists and is active
            result = await db.execute(
                select(User).where(User.id == user_id, User.email == email)
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.warning(f"User not found: id={user_id}, email={email}")
                return None, status.HTTP_401_UNAUTHORIZED

            if not user.is_active:
                logger.warning(f"User account inactive: id={user_id}")
                return None, status.HTTP_401_UNAUTHORIZED

            # Validate role
            try:
                user_role = UserRole(role)
            except ValueError:
                logger.warning(f"Invalid role in token: {role}")
                return None, status.HTTP_401_UNAUTHORIZED

            return TokenData(user_id=user_id, email=email, role=user_role), status.HTTP_200_OK

        except HTTPException:
            raise  # Re-raise existing HTTP exceptions
        except Exception as e:
            logger.error(f"Error getting current user: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    @staticmethod
    async def authenticate_user(
        email: str, password: str, db: AsyncSession
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Authenticate user with status codes"""
        try:
            from services.user_service import user_service
            
            # Get user by email
            user_data, status_code = await user_service.get_user_by_email(email, db)
            
            if status_code != status.HTTP_200_OK or not user_data:
                return None, status.HTTP_401_UNAUTHORIZED

            # Verify password
            is_valid, error = AuthService.verify_password(password, user_data["password_hash"])
            if not is_valid:
                logger.warning(f"Invalid password for user: {email}")
                return None, status.HTTP_401_UNAUTHORIZED
            if error:
                logger.error(f"Password verification error for user {email}: {error}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

            # Check if user is active
            if not user_data.get("is_active", False):
                logger.warning(f"Inactive user attempt: {email}")
                return None, status.HTTP_401_UNAUTHORIZED

            # Remove password hash from response
            user_data.pop("password_hash", None)
            return user_data, status.HTTP_200_OK

        except Exception as e:
            logger.error(f"Authentication error for user {email}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR


# Create global instance
auth_service = AuthService()