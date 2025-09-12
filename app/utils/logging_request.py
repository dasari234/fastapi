"""
Middleware for HTTP request logging.
"""

import time

from fastapi import Request
from loguru import logger

from app.utils.logging_config import get_access_logger

access_logger = get_access_logger()


async def log_requests_middleware(request: Request, call_next):
    """Middleware to log HTTP requests and responses."""
    start_time = time.time()
    
    # Log the incoming request
    logger.info(
        "HTTP Request: {} {} - Client: {}",
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown"
    )
    
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(
            "HTTP Error: {} {} - Error: {}",
            request.method,
            request.url.path,
            e
        )
        raise
    
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    
    # Log the response to access log
    access_logger.info(
        "{} {} - Status: {} - Time: {:.2f}ms - Client: {}",
        request.method,
        request.url.path,
        response.status_code,
        process_time,
        request.client.host if request.client else "unknown"
    )
    
    return response


