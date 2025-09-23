from typing import Any, Optional

from loguru import logger

from app.services import redis_service


def is_redis_available() -> bool:
    """Safely check if Redis is available"""
    try:
        # Check if redis_service exists and has the is_available property
        if hasattr(redis_service, 'is_available'):
            return redis_service.is_available
        return False
    except Exception as e:
        logger.debug(f"Error checking Redis availability: {e}")
        return False

async def safe_redis_get(key: str) -> Optional[Any]:
    """Safely get value from Redis"""
    if not is_redis_available():
        return None
    try:
        return await redis_service.get(key)
    except Exception as e:
        logger.debug(f"Redis get failed for {key}: {e}")
        return None

async def safe_redis_set(key: str, value: Any, ttl: int = None) -> bool:
    """Safely set value in Redis"""
    if not is_redis_available():
        return False
    try:
        return await redis_service.set(key, value, ttl)
    except Exception as e:
        logger.debug(f"Redis set failed for {key}: {e}")
        return False