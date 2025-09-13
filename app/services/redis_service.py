import json
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import CACHE_TTL_TOKEN, CACHE_TTL_USER
from app.redis.base_config import redis_pool


class RedisService:
    def __init__(self):
        self.redis = redis_pool
        self.initialized = redis_pool is not None
        self.connection_healthy = False
        
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
        if not self.initialized:
            return False
        
        if self.connection_healthy:
            return True
        
        try:
            # Test connection with a ping
            await self.redis.ping()
            self.connection_healthy = True
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
            if value is None:
                return None
                
            # Handle case where value might not be JSON
            try:
                parsed_value = json.loads(value)
                logger.debug(f"Redis get successful for key: {key}")
                return parsed_value
            except json.JSONDecodeError:
                # Return raw value if it's not JSON
                logger.debug(f"Redis get returned non-JSON value for key: {key}")
                return value
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            self.connection_healthy = False
            return None

    async def delete(self, key: str) -> bool:
        """Delete key"""
        if not await self._ensure_connection():
            logger.debug(f"Redis not available - skipping delete for key: {key}")
            return False
            
        try:
            result = await self.redis.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            self.connection_healthy = False
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not await self._ensure_connection():
            logger.debug(f"Redis not available - skipping exists check for key: {key}")
            return False
            
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            self.connection_healthy = False
            return False

    async def delete_pattern(self, pattern: str, batch_size: int = 1000) -> int:
        """Delete keys matching pattern using scan for better performance"""
        if not await self._ensure_connection():
            logger.debug(f"Redis not available - skipping pattern delete: {pattern}")
            return 0
            
        try:
            deleted_count = 0
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match=pattern, count=batch_size)
                if keys:
                    deleted = await self.redis.delete(*keys)
                    deleted_count += deleted
                if cursor == 0:
                    break
            return deleted_count
        except Exception as e:
            logger.error(f"Redis delete pattern error for {pattern}: {e}")
            self.connection_healthy = False
            return 0
        
    # Add a method to explicitly check connection health
    async def check_health(self) -> bool:
        """Explicit health check that can be called periodically"""
        try:
            if self.initialized and await self.redis.ping():
                self.connection_healthy = True
                return True
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
        self.connection_healthy = False
        return False
    

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
    async def cache_file(self, s3_key: str, file_data: Dict, ttl: int = 3600) -> bool:
        """Cache file data with TTL"""
        try:
            if not self.is_available():
                return False
                
            await self.redis_client.setex(
                f"file:{s3_key}",
                ttl,
                json.dumps(file_data)
            )
            logger.debug(f"Cached file data for key: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to cache file data: {e}")
            return False

    async def get_cached_file(self, s3_key: str) -> Optional[Dict]:
        """Get cached file data"""
        try:
            if not self.is_available():
                return None
                
            cached_data = await self.redis_client.get(f"file:{s3_key}")
            if cached_data:
                logger.debug(f"Cache hit for file: {s3_key}")
                return json.loads(cached_data)
            return None
        except Exception as e:
            logger.error(f"Failed to get cached file: {e}")
            return None

    async def invalidate_file_cache(self, s3_key: str) -> bool:
        """Invalidate cached file data"""
        try:
            if not self.is_available():
                return False
                
            await self.redis_client.delete(f"file:{s3_key}")
            logger.debug(f"Invalidated cache for file: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate file cache: {e}")
            return False

    async def cache_file_list(self, cache_key: str, files_data: List[Dict], ttl: int = 300) -> bool:
        """Cache file list data"""
        try:
            if not self.is_available():
                return False
                
            await self.redis_client.setex(
                cache_key,
                ttl,
                json.dumps(files_data)
            )
            logger.debug(f"Cached file list for key: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to cache file list: {e}")
            return False

    async def get_cached_file_list(self, cache_key: str) -> Optional[List[Dict]]:
        """Get cached file list"""
        try:
            if not self.is_available():
                return None
                
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for file list: {cache_key}")
                return json.loads(cached_data)
            return None
        except Exception as e:
            logger.error(f"Failed to get cached file list: {e}")
            return None
        
        
    async def invalidate_file_list_cache(self, cache_key: str) -> bool:
        """Invalidate file list cache"""
        try:
            if not self.is_available():
                return False
                
            # Use pattern matching to find and delete all related keys
            keys = await self.redis_client.keys(f"{cache_key}*")
            if keys:
                await self.redis_client.delete(*keys)
                logger.debug(f"Invalidated file list cache for pattern: {cache_key}*")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate file list cache: {e}")
            return False

    async def cache_file_metadata(self, s3_key: str, metadata: Dict, ttl: int = 3600) -> bool:
        """Cache file metadata separately"""
        try:
            if not self.is_available():
                return False
                
            await self.redis_client.setex(
                f"file_meta:{s3_key}",
                ttl,
                json.dumps(metadata)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to cache file metadata: {e}")
            return False

    async def get_cached_file_metadata(self, s3_key: str) -> Optional[Dict]:
        """Get cached file metadata"""
        try:
            if not self.is_available():
                return None
                
            cached_meta = await self.redis_client.get(f"file_meta:{s3_key}")
            if cached_meta:
                return json.loads(cached_meta)
            return None
        except Exception as e:
            logger.error(f"Failed to get cached file metadata: {e}")
            return None
        
        
    

# Global instance
redis_service = RedisService()






