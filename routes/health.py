import logging
import time

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from config import ENVIRONMENT
from database import get_db
from schemas import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
)
async def health_check(conn: asyncpg.Connection = Depends(get_db)):
    """Health check endpoint for NeonDB"""
    start_time = time.time()
    try:
        await conn.fetchval("SELECT 1")
        version_info = await conn.fetchval("SELECT version()")
        db_name = await conn.fetchval("SELECT current_database()")
        response_time = (time.time() - start_time) * 1000

        return HealthResponse(
            status="healthy",
            database="NeonDB",
            connection="active",
            database_name=db_name,
            postgresql_version=version_info.split()[1] if version_info else "unknown",
            environment=ENVIRONMENT,
            response_time_ms=response_time,
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database health check failed",
        )