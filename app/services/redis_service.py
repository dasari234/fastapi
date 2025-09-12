import json
from typing import Any, Optional

from loguru import logger

from app.config import CACHE_TTL_FILE, CACHE_TTL_TOKEN, CACHE_TTL_USER
from app.redis.base_config import redis_pool


class RedisService:
    def __init__(self):
        self.redis = redis_pool
        self.initialized = redis_pool is not None
        self.connection_healthy = False
        self._check_connection_health()
        
    def _check_connection_health(self):
        """Check if Redis connection is healthy"""
        if not self.initialized:
            logger.warning("Redis not initialized - running without caching")
            self.connection_healthy = False
            return
        
        try:
            # We'll check health on first use instead of blocking here
            self.connection_healthy = True
        except:
            self.connection_healthy = False
    
    async def _ensure_connection(self):
        """Ensure Redis connection is healthy"""
        if not self.initialized or not self.connection_healthy:
            return False
        
        try:
            # Test connection with a ping
            await self.redis.ping()
            return True
        except Exception as e:
            logger.warning(f"Redis connection unhealthy: {e}")
            self.connection_healthy = False
            return False
        
    def is_available(self) -> bool:
        """Check if Redis is available"""
        return self.initialized and self.connection_healthy

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value with optional TTL"""
        if not await self._ensure_connection():
            logger.debug(f"Redis not available - skipping set for key: {key}")
            return False
            
        try:
            serialized_value = json.dumps(value)
            if ttl:
                await self.redis.setex(key, ttl, serialized_value)
            else:
                await self.redis.set(key, serialized_value)
            logger.debug(f"Redis set successful for key: {key}")
            return True
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")
            self.connection_healthy = False
            return False

    async def get(self, key: str) -> Optional[Any]:
        """Get value by key"""
        if not await self._ensure_connection():
            logger.debug(f"Redis not available - skipping get for key: {key}")
            return None
            
        try:
            value = await self.redis.get(key)
            if value:
                logger.debug(f"Redis get successful for key: {key}")
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            self.connection_healthy = False
            return None

    async def delete(self, key: str) -> bool:
        """Delete key"""
        if not self.initialized or not self.redis:
            return False
            
        try:
            result = await self.redis.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self.initialized or not self.redis:
            return False
            
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern"""
        if not self.initialized or not self.redis:
            return 0
            
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                return await self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Redis delete pattern error for {pattern}: {e}")
            return 0

    # User-specific cache methods
    async def cache_user(self, user_id: int, user_data: dict) -> bool:
        """Cache user data"""
        return await self.set(f"user:{user_id}", user_data, CACHE_TTL_USER)

    async def get_cached_user(self, user_id: int) -> Optional[dict]:
        """Get cached user data"""
        return await self.get(f"user:{user_id}")

    async def invalidate_user(self, user_id: int) -> bool:
        """Invalidate user cache"""
        return await self.delete(f"user:{user_id}")

    async def invalidate_all_users(self) -> int:
        """Invalidate all user cache"""
        return await self.delete_pattern("user:*")

    # Email-based cache methods
    async def cache_user_by_email(self, email: str, user_data: dict) -> bool:
        """Cache user data by email"""
        return await self.set(f"user_email:{email}", user_data, CACHE_TTL_USER)

    async def get_cached_user_by_email(self, email: str) -> Optional[dict]:
        """Get cached user data by email"""
        return await self.get(f"user_email:{email}")

    async def invalidate_user_by_email(self, email: str) -> bool:
        """Invalidate user cache by email"""
        return await self.delete(f"user_email:{email}")

    # Token cache methods
    async def cache_token(self, token: str, user_data: dict) -> bool:
        """Cache token data"""
        return await self.set(f"token:{token}", user_data, CACHE_TTL_TOKEN)

    async def get_cached_token(self, token: str) -> Optional[dict]:
        """Get cached token data"""
        return await self.get(f"token:{token}")

    async def invalidate_token(self, token: str) -> bool:
        """Invalidate token cache"""
        return await self.delete(f"token:{token}")

    # File cache methods
    async def cache_file(self, s3_key: str, file_data: dict) -> bool:
        """Cache file data"""
        return await self.set(f"file:{s3_key}", file_data, CACHE_TTL_FILE)

    async def get_cached_file(self, s3_key: str) -> Optional[dict]:
        """Get cached file data"""
        return await self.get(f"file:{s3_key}")

    async def invalidate_file(self, s3_key: str) -> bool:
        """Invalidate file cache"""
        return await self.delete(f"file:{s3_key}")

# Global instance
redis_service = RedisService()






