"""
Global exception handling configuration.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger


async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for uncaught exceptions."""
    logger.error(
        "Unhandled exception: {} - Path: {} - Method: {}",
        exc,
        request.url.path,
        request.method,
        exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
    
    