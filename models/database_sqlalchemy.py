import logging
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_scoped_session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from fastapi import HTTPException, status

from config import SQLALCHEMY_DATABASE_URL, POOL_SIZE, MAX_OVERFLOW, POOL_TIMEOUT, POOL_RECYCLE
from models.database_models import Base

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
        import time
        now = time.time()
        
        # Skip frequent checks (check every 30 seconds)
        if now - self.last_check < 30:
            return self.is_healthy
            
        try:
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
                
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
        
        # Create async engine with connection pooling
        engine = create_async_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=POOL_RECYCLE,
            echo=False,
        )
        
        # Create session factory
        async_session_factory = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        session_factory = async_scoped_session(
            async_session_factory,
            scopefunc=asyncio.current_task
        )
        
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

async def close_db() -> None:
    """Close database connection pool"""
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database connection pool closed")

@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    if not engine:
        await init_db()
    
    session = session_factory()
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