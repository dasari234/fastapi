import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status

from config import ENVIRONMENT
from models.database import get_db
from models.schemas import HealthResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint for NeonDB"""
    start_time = time.time()
    try:
        # Test database connection
        await db.execute("SELECT 1")
        
        # Get database info
        version_info = await db.scalar("SELECT version()")
        db_name = await db.scalar("SELECT current_database()")
        
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
        response_time = (time.time() - start_time) * 1000
        return HealthResponse(
            status="unhealthy",
            database="NeonDB",
            connection="failed",
            database_name="unknown",
            postgresql_version="unknown",
            environment=ENVIRONMENT,
            response_time_ms=response_time,
        )

@router.get("/health/startup", include_in_schema=False)
async def startup_health_check():
    """Simple health check that doesn't depend on database."""
    return {"status": "healthy", "service": "bookstore-api"}

@router.get("/health/db", include_in_schema=False)
async def database_health_check():
    """Database-specific health check."""
    from models.database import health_checker
    
    if await health_checker.check_health():
        return {"status": "connected", "message": "Database is available"}
    else:
        return {
            "status": "disconnected",
            "message": "Database is not available",
            "error": "Database connection failed"
        }