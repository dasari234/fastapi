import logging
import time
from typing import Dict, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from config import ENVIRONMENT
from database import get_db
from schemas.health import HealthResponse, SimpleHealthResponse, DBHealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    responses={
        200: {"description": "Service is healthy and database is connected"},
        503: {"description": "Service is unhealthy or database connection failed"},
        500: {"description": "Internal server error during health check"}
    }
)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint for NeonDB with comprehensive status checking"""
    start_time = time.time()
    try:
        # Test database connection
        await db.execute(text("SELECT 1"))

        # Get database info
        version_info = await db.scalar(text("SELECT version()"))
        db_name = await db.scalar(text("SELECT current_database()"))

        response_time = (time.time() - start_time) * 1000

        return HealthResponse(
            success=True,
            status="healthy",
            database="NeonDB",
            connection="active",
            database_name=db_name,
            postgresql_version=version_info.split()[1] if version_info else "unknown",
            environment=ENVIRONMENT,
            response_time_ms=response_time,
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        response_time = (time.time() - start_time) * 1000
        
        # Determine appropriate status code
        if "connection" in str(e).lower() or "network" in str(e).lower():
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        
        return HealthResponse(
            success=False,
            status="unhealthy",
            database="NeonDB",
            connection="failed",
            database_name="unknown",
            postgresql_version="unknown",
            environment=ENVIRONMENT,
            response_time_ms=response_time,
            error=str(e),
            status_code=status_code
        )


@router.get(
    "/health/startup", 
    response_model=SimpleHealthResponse,
    summary="Startup Health Check",
    responses={
        200: {"description": "Service is healthy"},
        500: {"description": "Service startup check failed"}
    }
)
async def startup_health_check():
    """Simple health check that doesn't depend on database."""
    try:
        # Add any startup checks here (e.g., cache, external services)
        return SimpleHealthResponse(
            success=True,
            status="healthy",
            service="bookstore-api",
            message="Service is running",
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Startup health check failed: {e}")
        return SimpleHealthResponse(
            success=False,
            status="unhealthy",
            service="bookstore-api",
            error=f"Startup check failed: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.get(
    "/health/db", 
    response_model=DBHealthResponse,
    summary="Database Health Check",
    responses={
        200: {"description": "Database is connected and responsive"},
        503: {"description": "Database is not available"},
        500: {"description": "Database health check failed"}
    }
)
async def database_health_check(db: AsyncSession = Depends(get_db)):
    """Database-specific health check with detailed status."""
    try:
        # Test the connection with a simple query
        start_time = time.time()
        await db.execute(text("SELECT 1"))
        response_time = (time.time() - start_time) * 1000

        # Get additional database metrics
        db_name = await db.scalar(text("SELECT current_database()"))
        active_connections = await db.scalar(
            text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
        )

        return DBHealthResponse(
            success=True,
            status="connected",
            message=f"Database '{db_name}' is available ({active_connections} active connections, {response_time:.2f}ms response)",
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        
        # Differentiate between connection errors and other errors
        error_msg = str(e)
        if "connection" in error_msg.lower() or "network" in error_msg.lower():
            return DBHealthResponse(
                success=False,
                status="disconnected",
                message="Database connection failed",
                error=error_msg,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        else:
            return DBHealthResponse(
                success=False,
                status="error",
                message="Database health check failed",
                error=error_msg,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@router.get(
    "/health/detailed",
    response_model=Dict[str, Any],
    summary="Detailed Health Check",
    responses={
        200: {"description": "Comprehensive health status report"},
        207: {"description": "Partial success - some components unhealthy"},
        503: {"description": "Critical components unavailable"}
    }
)
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check with multiple component statuses."""
    components = {}
    overall_status = "healthy"
    has_critical_failures = False
    
    try:
        # Check database
        db_start = time.time()
        await db.execute(text("SELECT 1"))
        db_time = (time.time() - db_start) * 1000
        components["database"] = {
            "status": "healthy",
            "response_time_ms": db_time,
            "message": "Database connection successful"
        }
    except Exception as e:
        components["database"] = {
            "status": "unhealthy",
            "error": str(e),
            "message": "Database connection failed"
        }
        overall_status = "degraded"
        has_critical_failures = True
    
    # Add other component checks here (cache, external APIs, etc.)
    components["api_service"] = {
        "status": "healthy",
        "message": "API service is running"
    }
    
    # Determine overall status code
    if has_critical_failures:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif overall_status == "degraded":
        status_code = status.HTTP_207_MULTI_STATUS
    else:
        status_code = status.HTTP_200_OK
    
    return {
        "success": not has_critical_failures,
        "status": overall_status,
        "components": components,
        "environment": ENVIRONMENT,
        "timestamp": time.time(),
        "status_code": status_code
    }