import asyncio
import os
from typing import Optional

import redis.asyncio as redis
from loguru import logger

from app.config import (REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT,
                        REDIS_SSL)


class RedisConfig:
    REDIS_HOST = REDIS_HOST
    REDIS_PORT = REDIS_PORT
    REDIS_PASSWORD = REDIS_PASSWORD
    REDIS_DB = REDIS_DB
    REDIS_SSL = REDIS_SSL
    
    # Connection settings
    REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", 5))
    REDIS_TIMEOUT = int(os.getenv("REDIS_TIMEOUT", 3))
    REDIS_CONNECT_TIMEOUT = int(os.getenv("REDIS_CONNECT_TIMEOUT", 5))
    REDIS_RETRY_ATTEMPTS = int(os.getenv("REDIS_RETRY_ATTEMPTS", 2))

redis_config = RedisConfig()

# Global Redis connection pool
redis_pool: Optional[redis.Redis] = None

async def get_redis_connection() -> Optional[redis.Redis]:
    """Get Redis connection with retry logic"""
    for attempt in range(redis_config.REDIS_RETRY_ATTEMPTS):
        try:
            connection = redis.Redis(
                host=redis_config.REDIS_HOST,
                port=redis_config.REDIS_PORT,
                password=redis_config.REDIS_PASSWORD or None,
                db=redis_config.REDIS_DB,
                ssl=redis_config.REDIS_SSL,
                ssl_cert_reqs=None,
                max_connections=redis_config.REDIS_MAX_CONNECTIONS,
                socket_timeout=redis_config.REDIS_TIMEOUT,
                socket_connect_timeout=redis_config.REDIS_CONNECT_TIMEOUT,
                decode_responses=True,
                retry_on_timeout=True,
                health_check_interval=30
            )
            
            # Test connection
            await connection.ping()
            logger.success(f"Redis connection established to {redis_config.REDIS_HOST}:{redis_config.REDIS_PORT}")
            return connection
            
        except Exception as e:
            if attempt == redis_config.REDIS_RETRY_ATTEMPTS - 1:
                logger.error(f"Failed to connect to Redis after {redis_config.REDIS_RETRY_ATTEMPTS} attempts: {e}")
                return None
            logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(1)  # Wait before retry

async def init_redis_pool() -> Optional[redis.Redis]:
    """Initialize Redis connection pool"""
    global redis_pool
    try:
        redis_pool = await get_redis_connection()
        if redis_pool:
            logger.success("Redis connection pool initialized successfully")
        else:
            logger.warning("Redis connection failed - running without Redis caching")
        return redis_pool
    except Exception as e:
        logger.error(f"Unexpected error initializing Redis: {e}")
        return None

async def close_redis_pool():
    """Close Redis connection pool"""
    global redis_pool
    if redis_pool:
        try:
            await redis_pool.close()
            logger.info("Redis connection pool closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
        finally:
            redis_pool = None
            

            
                        
            