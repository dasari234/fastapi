"""
Database connection and session management module for FastAPI applications.

This module provides async database operations with connection pooling,
health monitoring, and comprehensive error handling.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Optional, Any
from enum import Enum

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from config import (
    DEBUG,
    MAX_OVERFLOW,
    POOL_RECYCLE,
    POOL_SIZE,
    POOL_TIMEOUT,
    SQLALCHEMY_DATABASE_URL,
    SSL_MODE,
)
from schemas.base import Base


class DatabaseStatus(Enum):
    """Database connection status enumeration"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    NOT_INITIALIZED = "not_initialized"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class DatabaseError(Exception):
    """Custom database error exception"""

    def __init__(self, message: str, status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class DatabaseHealthChecker:
    """
    Database connection health monitoring with exponential backoff.
    """

    def __init__(
        self,
        check_interval: int = 30,
        max_consecutive_failures: int = 3,
        backoff_multiplier: float = 2.0,
        max_backoff: int = 300,
    ):
        self.last_check = 0.0
        self.is_healthy = True
        self.consecutive_failures = 0
        self.check_interval = check_interval
        self.max_consecutive_failures = max_consecutive_failures
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff = max_backoff
        self.last_error: Optional[str] = None
        self.last_successful_check = time.time()

        logger.info(
            "Database health checker initialized (interval: {}s, max failures: {})",
            check_interval,
            max_consecutive_failures,
        )

    def _calculate_backoff_interval(self) -> float:
        if self.consecutive_failures <= 1:
            return self.check_interval
        backoff = self.check_interval * (self.backoff_multiplier ** (self.consecutive_failures - 1))
        return min(backoff, self.max_backoff)

    async def check_health(self, engine: AsyncEngine) -> bool:
        current_time = time.time()
        required_interval = self._calculate_backoff_interval()

        if current_time - self.last_check < required_interval:
            logger.debug("Health check skipped (next check in {:.1f}s)", required_interval - (current_time - self.last_check))
            return self.is_healthy

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1 as health_check"))
                if result.scalar() != 1:
                    raise Exception("Health check query returned unexpected value")

            self._reset_failure_tracking(current_time)
            logger.debug("Database health check passed")
            return True
        except Exception as e:
            self._handle_failure(e, current_time)
            return False

    def _reset_failure_tracking(self, current_time: float) -> None:
        if not self.is_healthy or self.consecutive_failures > 0:
            logger.info("Database connection restored after {} failures", self.consecutive_failures)
        self.is_healthy = True
        self.consecutive_failures = 0
        self.last_check = current_time
        self.last_successful_check = current_time
        self.last_error = None

    def _handle_failure(self, error: Exception, current_time: float) -> None:
        self.consecutive_failures += 1
        self.is_healthy = False
        self.last_check = current_time
        self.last_error = str(error)

        logger.warning("Database health check failed (attempt {}): {}", self.consecutive_failures, error)

        if self.consecutive_failures >= self.max_consecutive_failures:
            logger.error(
                "Database connection appears down after {} consecutive failures. "
                "Last success: {:.1f}s ago",
                self.consecutive_failures,
                current_time - self.last_successful_check,
            )

    def get_metrics(self) -> Dict[str, Any]:
        current_time = time.time()
        return {
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "last_check": self.last_check,
            "last_successful_check": self.last_successful_check,
            "time_since_last_check": current_time - self.last_check,
            "time_since_last_success": current_time - self.last_successful_check,
            "last_error": self.last_error,
            "next_check_in": max(0, self._calculate_backoff_interval() - (current_time - self.last_check)),
        }


class DatabaseManager:
    """Database connection manager with comprehensive error handling."""

    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._async_session_factory: Optional[sessionmaker] = None
        self._session_factory: Optional[async_scoped_session] = None
        self._health_checker = DatabaseHealthChecker()
        self._init_lock = asyncio.Lock()
        logger.info("Database manager initialized")

    def _get_ssl_connect_args(self) -> Dict[str, Any]:
        ssl_configs = {
            "require": {"ssl": "require"},
            "prefer": {"ssl": True},
            "disable": {"ssl": False},
            "verify-ca": {"ssl": "verify-full"},
            "verify-full": {"ssl": "verify-full"},
        }
        return ssl_configs.get(SSL_MODE, {"ssl": True})

    async def _build_engine(self, ssl_enabled: bool = True) -> AsyncEngine:
        connect_args = self._get_ssl_connect_args() if ssl_enabled else {"ssl": False}
        return create_async_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=POOL_RECYCLE,
            echo=DEBUG,
            pool_pre_ping=True,
            connect_args=connect_args,
            pool_reset_on_return="commit",
            future=True,
        )

    async def _initialize(self, ssl_enabled: bool = True) -> None:
        async with self._init_lock:
            if self._engine:
                logger.debug("Database already initialized, skipping")
                return

            logger.info("Initializing database connection (SSL={})", ssl_enabled)
            try:
                self._engine = await self._build_engine(ssl_enabled)
                await self._create_session_factories()
                await self._create_tables()
                await self._verify_connection()
                logger.success("Database initialized successfully (SSL={})", ssl_enabled)
            except Exception as e:
                await self.close_connection()
                logger.error(f"Database initialization failed: {e}")
                raise DatabaseError(str(e))

    async def _create_session_factories(self) -> None:
        self._async_session_factory = sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            future=True,
        )
        self._session_factory = async_scoped_session(
            self._async_session_factory,
            scopefunc=asyncio.current_task,
        )

    async def _create_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def _verify_connection(self) -> None:
        if not await self._health_checker.check_health(self._engine):
            raise DatabaseError("Initial database health check failed")

    async def initialize_database(self) -> None:
        await self._initialize(ssl_enabled=True)

    async def initialize_without_ssl(self) -> None:
        await self._initialize(ssl_enabled=False)

    async def close_connection(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._async_session_factory = None
            self._session_factory = None
            logger.info("Database connection closed")

    async def ensure_initialized(self) -> bool:
        if not self._engine:
            await self.initialize_database()
            return True

        if not await self._health_checker.check_health(self._engine):
            logger.warning("Database unhealthy, reinitializing")
            await self.close_connection()
            await self.initialize_database()

        return True

    @asynccontextmanager
    async def session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        await self.ensure_initialized()
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            if isinstance(e, DisconnectionError):
                self._health_checker.is_healthy = False
            logger.error(f"Database error: {e}")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database operation failed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Unexpected session error: {e}")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")
        finally:
            await session.close()

    async def verify_health(self) -> bool:
        return await self._health_checker.check_health(self._engine) if self._engine else False

    def get_stats(self) -> Dict[str, Any]:
        if not self._engine:
            return {"status": DatabaseStatus.NOT_INITIALIZED.value}
        try:
            pool = self._engine.pool
            metrics = self._health_checker.get_metrics()
            return {
                "status": DatabaseStatus.HEALTHY.value if metrics["is_healthy"] else DatabaseStatus.UNHEALTHY.value,
                "pool_size": POOL_SIZE,
                "max_overflow": MAX_OVERFLOW,
                "pool_timeout": POOL_TIMEOUT,
                "pool_recycle": POOL_RECYCLE,
                "ssl_mode": SSL_MODE,
                "health_metrics": metrics,
                "pool_stats": {
                    "size": pool.size() if hasattr(pool, "size") else None,
                    "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else None,
                    "overflow": pool.overflow() if hasattr(pool, "overflow") else None,
                },
            }
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {"status": DatabaseStatus.ERROR.value, "error": str(e)}


# Global instance
_db_manager = DatabaseManager()

# Public interface
async def init_db() -> None:
    await _db_manager.initialize_database()

async def init_db_without_ssl() -> None:
    await _db_manager.initialize_without_ssl()

async def close_db() -> None:
    await _db_manager.close_connection()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _db_manager.session_scope() as session:
        yield session

@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    async with _db_manager.session_scope() as session:
        yield session

async def ensure_db_initialized() -> bool:
    return await _db_manager.ensure_initialized()

async def get_database_stats() -> Dict[str, Any]:
    return _db_manager.get_stats()

async def health_check() -> bool:
    return await _db_manager.verify_health()


__all__ = [
    "init_db",
    "init_db_without_ssl",
    "close_db",
    "get_db",
    "get_db_context",
    "ensure_db_initialized",
    "get_database_stats",
    "health_check",
    "DatabaseError",
    "DatabaseStatus",
]
