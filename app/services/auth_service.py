from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt
from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from loguru import logger
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
)
from app.hooks.notification_hooks import notify_login
from app.models.user import TokenBlacklist
from app.schemas.auth import TokenData
from app.utils.redis_utils import is_redis_available, safe_redis_get, safe_redis_set

# --- Password hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- OAuth2 scheme ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class AuthService:
    @staticmethod
    def verify_password(
        plain_password: str, hashed_password: str
    ) -> Tuple[bool, Optional[str]]:
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
            expire = datetime.now(timezone.utc) + timedelta(
                days=REFRESH_TOKEN_EXPIRE_DAYS
            )
            to_encode.update({"exp": expire})
            encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
            return encoded_jwt, status.HTTP_200_OK
        except jwt.PyJWTError as e:
            logger.error(f"JWT encoding error for refresh token: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        except Exception as e:
            logger.error(f"Failed to create refresh token: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    async def verify_token(self, token: str, db: AsyncSession = None) -> Tuple[Optional[Dict[str, Any]], int]:
        """Verify JWT token with Redis caching and database fallback"""
        try:
            # Basic token validation
            if not token or not isinstance(token, str):
                return None, status.HTTP_401_UNAUTHORIZED
            
            # Check token structure (should have 3 parts)
            if len(token.split('.')) != 3:
                return None, status.HTTP_401_UNAUTHORIZED
            
            # Check Redis cache first if available
            if is_redis_available():
                cache_key = f"token_blacklist:{token}"
                cached_blacklist = await safe_redis_get(cache_key)
                
                if cached_blacklist is not None:
                    if cached_blacklist.get("blacklisted", False):
                        logger.warning(f"Attempt to use blacklisted token (from cache): {token}")
                        return None, status.HTTP_401_UNAUTHORIZED
                    # Token is not blacklisted in cache, proceed with JWT verification
                else:
                    # Cache miss - need to check database
                    if db is None:
                        from app.database import get_db_context
                        async with get_db_context() as session:
                            return await self._verify_token_with_session(token, session)
                    else:
                        return await self._verify_token_with_session(token, db)
            else:
                # Redis not available, check database directly
                if db is None:
                    from app.database import get_db_context
                    async with get_db_context() as session:
                        return await self._verify_token_with_session(token, session)
                else:
                    return await self._verify_token_with_session(token, db)
            
            # If we reach here, token is not blacklisted (from cache), verify JWT
            try:
                # Try to decode without verification first to check expiration
                try:
                    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
                except jwt.PyJWTError:
                    # If we can't even decode without verification, it's invalid
                    return None, status.HTTP_401_UNAUTHORIZED
                
                # Now verify with expiration check
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

    async def _verify_token_with_session(
        self, token: str, session: AsyncSession
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Internal method to verify token with database session"""
        try:
            from sqlalchemy import select

            # Check database for blacklist status
            result = await session.execute(
                select(TokenBlacklist).where(TokenBlacklist.token == token)
            )
            blacklisted = result.scalar_one_or_none()

            cache_key = f"token_blacklist:{token}"

            # Update Redis cache if available
            if is_redis_available():
                if blacklisted:
                    # Cache blacklisted status
                    await safe_redis_set(cache_key, {"blacklisted": True}, ttl=300)
                else:
                    # Cache non-blacklisted status
                    await safe_redis_set(cache_key, {"blacklisted": False}, ttl=60)

            if blacklisted:
                logger.warning(f"Attempt to use blacklisted token: {token}")
                return None, status.HTTP_401_UNAUTHORIZED

            # Verify JWT token
            try:
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
            logger.error(f"Error in token verification with session: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    async def get_current_user(
        self, token: str = Depends(oauth2_scheme)
    ) -> Tuple[Optional[TokenData], int]:
        """Get current user from token - returns (user_data, status_code)"""
        try:
            # Import user_service locally to avoid circular imports
            from app.services.user_service import user_service

            # Check cache first if Redis is available
            if is_redis_available():
                cached_user = await safe_redis_get(f"token:{token}")
                if cached_user:
                    logger.debug("User data retrieved from Redis cache")
                    return TokenData(**cached_user), status.HTTP_200_OK

            # Verify token with database session
            from app.database import get_db_context

            async with get_db_context() as db:
                payload, status_code = await self.verify_token(token, db)

                if status_code != status.HTTP_200_OK or not payload:
                    return None, status.HTTP_401_UNAUTHORIZED

                # Extract user data
                user_id = payload.get("user_id")
                email = payload.get("email")
                role = payload.get("role", "user")

                if not user_id or not email:
                    return None, status.HTTP_401_UNAUTHORIZED

                # Get user data from database using the same session
                user_data, user_status = await user_service.get_user_by_id(user_id, db)

                if user_status != status.HTTP_200_OK or not user_data:
                    return None, status.HTTP_401_UNAUTHORIZED

                # Create TokenData object
                user_data_obj = TokenData(
                    user_id=user_id, email=email, role=role, token=token
                )

                # Cache the user data if Redis is available
                if is_redis_available():
                    await safe_redis_set(
                        f"token:{token}", user_data_obj.model_dump(), ttl=300
                    )

                return user_data_obj, status.HTTP_200_OK

        except Exception as e:
            logger.error(f"Error getting current user: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    async def invalidate_token(
        self, token: str, db: AsyncSession = None
    ) -> Tuple[bool, int]:
        """
        Invalidate a JWT token by adding it to the blacklist
        Optimized to avoid duplicate checks
        """

        async def _invalidate_token(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # First check cache if Redis is available
                if is_redis_available():
                    cache_key = f"token_blacklist:{token}"
                    cached_check = await safe_redis_get(cache_key)

                    if cached_check and cached_check.get("blacklisted", False):
                        logger.info(f"Token already blacklisted (from cache): {token}")
                        return True, status.HTTP_200_OK

                # Check if token is already blacklisted in database
                from sqlalchemy import select

                result = await session.execute(
                    select(TokenBlacklist).where(TokenBlacklist.token == token)
                )
                existing_token = result.scalar_one_or_none()

                if existing_token:
                    logger.info(f"Token already blacklisted: {token}")
                    # Cache this result if Redis is available
                    if is_redis_available():
                        await safe_redis_set(cache_key, {"blacklisted": True}, ttl=3600)
                    return True, status.HTTP_200_OK

                # Add token to blacklist
                blacklisted_token = TokenBlacklist(
                    token=token, blacklisted_at=datetime.now(timezone.utc)
                )

                session.add(blacklisted_token)
                await session.commit()

                # Cache the blacklist status if Redis is available
                if is_redis_available():
                    await safe_redis_set(cache_key, {"blacklisted": True}, ttl=3600)

                logger.info("Token successfully blacklisted for user")
                return True, status.HTTP_200_OK

            except Exception as e:
                await session.rollback()
                logger.error(f"Error invalidating token: {e}", exc_info=True)
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _invalidate_token(db)
        else:
            from app.database import get_db_context

            async with get_db_context() as session:
                return await _invalidate_token(session)

    async def authenticate_user(
        self,
        email: str,
        password: str,
        db: AsyncSession,
        ip_address: str = None,
        user_agent: str = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Authenticate user with status codes and login history"""
        try:
            # Import services locally to avoid circular imports
            from app.services.login_history_service import create_login_record
            from app.services.user_service import user_service

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
                    failure_reason="Invalid password",
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
                    failure_reason="Account deactivated",
                )
                return None, status.HTTP_401_UNAUTHORIZED

            # Create successful login record
            await create_login_record(
                db=db,
                user_id=user_data["id"],
                ip_address=ip_address,
                user_agent=user_agent,
                login_status="success",
            )

            # Remove password hash from response
            user_data.pop("password_hash", None)

            # Send login notification
            if user_data and status_code == status.HTTP_200_OK:
                login_data = {
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                import asyncio

                asyncio.create_task(notify_login(user_data["id"], login_data, db))

            return user_data, status.HTTP_200_OK

        except Exception as e:
            logger.error(f"Authentication error for user {email}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    def get_current_user_dependency(self):
        """Return a dependency function"""

        async def _get_current_user(
            token: str = Depends(oauth2_scheme),
        ) -> Tuple[Optional[TokenData], int]:
            return await self.get_current_user(token)

        return _get_current_user

    @staticmethod
    def is_token_expired(token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Check if token is expired without full verification"""
        try:
            # Decode without verification to get payload
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
            
            # Check expiration manually
            exp = payload.get('exp')
            if exp is None:
                return True, payload  # No expiration date, consider expired
            
            current_time = datetime.now(timezone.utc).timestamp()
            if current_time > exp:
                return True, payload  # Token is expired
            
            return False, payload  # Token is not expired
            
        except jwt.PyJWTError as e:
            logger.error(f"Error checking token expiration: {e}")
            return True, None
        

# --- Create global instance ---
auth_service = AuthService()
