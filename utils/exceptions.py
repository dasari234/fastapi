import logging

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from schemas.base import ErrorResponse

logger = logging.getLogger(__name__)

async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI validation errors."""
    logger.warning("Validation error: %s", exc.errors())
    error_response = ErrorResponse(
        error="Validation Error",
        detail=exc.errors(),
        status_code=422,
    )
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(error_response),
    )

async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Handle FastAPI HTTP exceptions."""
    logger.warning("HTTP error %d: %s", exc.status_code, exc.detail)
    error_response = ErrorResponse(
        error=str(exc.detail),
        detail=None,
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(error_response),
    )

async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Handle uncaught exceptions."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    error_response = ErrorResponse(
        error="Internal Server Error",
        detail=str(exc),
        status_code=500,
    )
    return JSONResponse(
        status_code=500,
        content=jsonable_encoder(error_response),
    )