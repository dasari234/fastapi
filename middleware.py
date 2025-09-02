import logging
import time

from fastapi import Request, Response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def add_process_time_header(request: Request, call_next) -> Response:
    """
    Middleware to add X-Process-Time header and log request details.
    """
    start_time = time.time()
    response: Response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    logger.info(
        "%s %s - %d - %.2fms",
        request.method,
        request.url.path,
        response.status_code,
        process_time,
    )
    return response
