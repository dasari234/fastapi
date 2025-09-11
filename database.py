"""
Database connection and session management module for FastAPI applications.
Provides async database operations with connection pooling and health monitoring.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_scoped_session, create_async_engine)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from config import (DEBUG, MAX_OVERFLOW, POOL_RECYCLE, POOL_SIZE, POOL_TIMEOUT,
                    SQLALCHEMY_DATABASE_URL, SSL_MODE)
from schemas.base import Base

# Global engine and session factory
_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[sessionmaker] = None
_session_factory: Optional[async_scoped_session] = None


class DatabaseHealthChecker:
    """Monitor database connection health with exponential backoff."""
    
    def __init__(self, check_interval: int = 30, max_consecutive_failures: int = 3):
        self.last_check = 0
        self.is_healthy = True
        self.consecutive_failures = 0
        self.check_interval = check_interval
        self.max_consecutive_failures = max_consecutive_failures
        
    async def check_health(self) -> bool:
        """Check if database connection is healthy with exponential backoff."""
        global _engine
        
        now = time.time()
        
        # Skip frequent checks
        if now - self.last_check < self.check_interval:
            return self.is_healthy
            
        try:
            async with _engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                
            self.is_healthy = True
            self.consecutive_failures = 0
            self.last_check = now
            logger.debug("Database health check passed")
            return True
            
        except Exception as e:
            self.consecutive_failures += 1
            self.is_healthy = False
            logger.warning(
                f"Database health check failed (attempt {self.consecutive_failures}): {e}"
            )
            
            if self.consecutive_failures >= self.max_consecutive_failures:
                logger.error(
                    "Database connection appears to be down after multiple health check failures"
                )
                
            return False


# Global health checker instance
_health_checker = DatabaseHealthChecker()


def _get_ssl_connect_args() -> dict:
    """Get SSL connection arguments based on SSL_MODE configuration."""
    ssl_modes = {
        'require': {'ssl': 'require'},
        'prefer': {'ssl': True},
        'disable': {'ssl': False},
        'verify-ca': {'ssl': 'verify-full'},
        'verify-full': {'ssl': 'verify-full'}
    }
    
    return ssl_modes.get(SSL_MODE, {'ssl': True})


async def init_db() -> None:
    """Initialize database connection pool and create tables."""
    global _engine, _async_session_factory, _session_factory
    
    try:
        logger.info("Initializing SQLAlchemy database connection...")
        
        # Create async engine with connection pooling
        _engine = create_async_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=POOL_RECYCLE,
            echo=DEBUG,
            pool_pre_ping=True,
            connect_args=_get_ssl_connect_args()
        )
        
        # Create session factory
        _async_session_factory = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        
        _session_factory = async_scoped_session(
            _async_session_factory,
            scopefunc=asyncio.current_task
        )
        
        # Create tables
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        # Initial health check
        await _health_checker.check_health()
        
        logger.info("SQLAlchemy database initialized successfully")
        
    except OperationalError as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed"
        )
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database initialization failed: {str(e)}"
        )


async def init_db_without_ssl() -> None:
    """Initialize database without SSL."""
    global _engine, _async_session_factory, _session_factory
    
    logger.info("Attempting database connection without SSL...")
    
    # Create async engine without SSL
    _engine = create_async_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=POOL_RECYCLE,
        echo=DEBUG,
        pool_pre_ping=True,
        connect_args={'ssl': False}
    )
    
    # Create session factory
    _async_session_factory = sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )
    
    _session_factory = async_scoped_session(
        _async_session_factory,
        scopefunc=asyncio.current_task
    )
    
    # Test connection
    async with _engine.connect() as test_conn:
        await test_conn.execute(text("SELECT 1"))
        logger.info("Database connection test successful without SSL")

    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _health_checker.check_health()
    logger.info("SQLAlchemy database initialized without SSL")


async def close_db() -> None:
    """Close database connection pool."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("Database connection pool closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session (for use as FastAPI dependency)."""
    await ensure_db_initialized()
    
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database operation failed"
            )
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager to get database session (for use in service methods)."""
    await ensure_db_initialized()
    
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database operation failed"
            )
        finally:
            await session.close()


async def ensure_db_initialized() -> bool:
    """Ensure database is initialized and healthy."""
    global _engine, _health_checker
    
    if not _engine:
        await init_db()
    elif not await _health_checker.check_health():
        logger.warning("Database pool is unhealthy. Reinitializing...")
        await close_db()
        await init_db()
    
    return True


async def get_database_stats() -> dict:
    """Get database connection pool statistics."""
    global _engine, _health_checker
    
    if not _engine:
        return {"status": "not_initialized"}
    
    try:
        return {
            "status": "healthy" if _health_checker.is_healthy else "unhealthy",
            "pool_size": POOL_SIZE,
            "max_overflow": MAX_OVERFLOW,
            "consecutive_failures": _health_checker.consecutive_failures,
            "last_health_check": _health_checker.last_check,
            "current_time": time.time()
        }
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return {"status": "error", "error": str(e)}


# Export public interface
__all__ = [
    'init_db',
    'init_db_without_ssl',
    'close_db',
    'get_db',
    'get_db_context',
    'ensure_db_initialized',
    'get_database_stats'
]
