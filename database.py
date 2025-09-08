import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import HTTPException, status
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (AsyncSession, async_scoped_session,
                                    create_async_engine)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from config import (DEBUG, MAX_OVERFLOW, POOL_RECYCLE, POOL_SIZE, POOL_TIMEOUT,
                    SQLALCHEMY_DATABASE_URL, SSL_MODE)
from schemas.base import Base


logger = logging.getLogger(__name__)

# Global engine and session factory
engine = None
async_session_factory = None
session_factory = None

class DatabaseHealthChecker:
    """Monitor database connection health"""
    
    def __init__(self):
        self.last_check = 0
        self.is_healthy = True
        self.consecutive_failures = 0
        
    async def check_health(self) -> bool:
        """Check if database connection is healthy"""
        global engine
        now = time.time()
        
        # Skip frequent checks (check every 30 seconds)
        if now - self.last_check < 30:
            return self.is_healthy
            
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                
            self.is_healthy = True
            self.consecutive_failures = 0
            self.last_check = now
            return True
            
        except Exception as e:
            self.consecutive_failures += 1
            self.is_healthy = False
            logger.warning(f"Database health check failed (attempt {self.consecutive_failures}): {e}")
            
            if self.consecutive_failures >= 3:
                logger.error("Database connection appears to be down after multiple health check failures")
                
            return False

# Global health checker instance
health_checker = DatabaseHealthChecker()

async def init_db() -> None:
    """Initialize database connection pool and create tables"""
    global engine, async_session_factory, session_factory
    
    try:
        logger.info("Initializing SQLAlchemy database connection...")
        
        # Configure SSL parameters for asyncpg
        connect_args = {}
        if SSL_MODE == 'require':
            connect_args['ssl'] = 'require'
        elif SSL_MODE == 'prefer':
            connect_args['ssl'] = True
        elif SSL_MODE == 'disable':
            connect_args['ssl'] = False
        elif SSL_MODE in ('verify-ca', 'verify-full'):
            connect_args['ssl'] = 'verify-full'
        else:
            connect_args['ssl'] = True
        
        # Create async engine with connection pooling
        engine = create_async_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=POOL_RECYCLE,
            echo=DEBUG,
            pool_pre_ping=True,
            connect_args=connect_args
        )
        
        # Create session factory
        async_session_factory = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        session_factory = async_session_factory
        
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        # Initial health check
        await health_checker.check_health()
        
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
        
async def init_db_without_ssl():
    """Initialize database without SSL"""
    global engine, async_session_factory, session_factory
    
    logger.info("Attempting database connection without SSL...")
    
    # Create async engine without SSL
    engine = create_async_engine(
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
    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    session_factory = async_scoped_session(
        async_session_factory,
        scopefunc=asyncio.current_task
    )
    
    # Test connection
    async with engine.connect() as test_conn:
        await test_conn.execute(text("SELECT 1"))
        logger.info("Database connection test successful without SSL")

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await health_checker.check_health()
    logger.info("SQLAlchemy database initialized without SSL")
                
async def close_db() -> None:
    """Close database connection pool"""
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database connection pool closed")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session (for use as FastAPI dependency)"""
    if not engine:
        await init_db()
    
    async with session_factory() as session:
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
    """Context manager to get database session (for use in service methods)"""
    if not engine:
        await init_db()
    
    async with session_factory() as session:
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
    """Ensure database is initialized"""
    global engine
    if not engine:
        await init_db()
    elif not await health_checker.check_health():
        logger.warning("Database pool is unhealthy. Reinitializing...")
        await close_db()
        await init_db()
    
    return True

async def get_database_stats() -> dict:
    """Get database connection pool statistics"""
    if not engine:
        return {"status": "not_initialized"}
    
    try:
        return {
            "status": "healthy" if health_checker.is_healthy else "unhealthy",
            "pool_size": POOL_SIZE,
            "max_overflow": MAX_OVERFLOW,
            "consecutive_failures": health_checker.consecutive_failures,
            "last_health_check": health_checker.last_check
        }
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return {"status": "error", "error": str(e)}
    
    