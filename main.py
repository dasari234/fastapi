import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum

from config import DEBUG, ENVIRONMENT
from database import (add_versioning_columns, close_db, ensure_db_initialized,
                      init_db)
from exceptions import (generic_exception_handler, http_exception_handler,
                        validation_exception_handler)
from middleware import add_process_time_header
from routes.books import router as books_router
from routes.files import router as files_router
from routes.health import router as health_router
from routes.root import router as root_router


# --- Logging Configuration ---
def setup_logging():
    """Configure logging with proper formatting and handlers."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if ENVIRONMENT == "production":
        # Add file handler for production
        file_handler = logging.FileHandler("app.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    
    logging.basicConfig(
        level=logging.INFO if ENVIRONMENT == "production" else logging.DEBUG,
        format=log_format,
        handlers=handlers,
        force=True  # Override any existing configuration
    )
    
    # Set specific loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    
    return logging.getLogger(__name__)

logger = setup_logging()

# --- Database Initialization Error Handler ---
class DatabaseInitializationError(Exception):
    """Custom exception for database initialization failures."""
    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        self.message = message
        self.original_exception = original_exception
        super().__init__(self.message)

# --- Database Connection State ---
class DatabaseState:
    """Track database connection state."""
    def __init__(self):
        self.is_connected = False
        self.initialization_error = None
        self.retry_count = 0
        self.max_retries = 3

# Initialize database state
db_state = DatabaseState()

# --- Safe Database Initialization ---
async def safe_init_db():
    """Safely initialize database with retry logic."""
    import asyncio
    import re
    
    for attempt in range(db_state.max_retries):
        try:
            logger.info(f"Database initialization attempt {attempt + 1}/{db_state.max_retries}")
            await init_db()
            db_state.is_connected = True
            db_state.initialization_error = None
            db_state.retry_count = attempt
            logger.info("Database initialized successfully")
            return True
            
        except HTTPException as http_exc:
            error_msg = f"Database HTTP error: Status {http_exc.status_code}"
            if hasattr(http_exc, 'detail') and http_exc.detail:
                # Safely extract detail, avoiding format issues
                try:
                    detail = str(http_exc.detail)
                    # Clean the detail string to avoid format issues
                    clean_detail = re.sub(r'[^\w\s\-\.\,\:\(\)]', '', detail)
                    if clean_detail.strip():
                        error_msg += f" - {clean_detail}"
                except:
                    error_msg += " - (detail unavailable)"
            
            logger.error(f"Attempt {attempt + 1} failed: {error_msg}")
            db_state.initialization_error = error_msg
            db_state.retry_count = attempt + 1
            
            if attempt < db_state.max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            
        except Exception as e:
            # Clean any problematic characters from error message
            try:
                error_str = str(e)
                clean_error = re.sub(r'[^\w\s\-\.\,\:\(\)]', '', error_str)
                error_msg = f"Database error: {clean_error}" if clean_error.strip() else "Database initialization error"
            except:
                error_msg = "Database initialization error (details unavailable)"
            
            logger.error(f"Attempt {attempt + 1} failed: {error_msg}")
            db_state.initialization_error = error_msg
            db_state.retry_count = attempt + 1
            
            if attempt < db_state.max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    db_state.is_connected = False
    return False

# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events with graceful database handling.
    """
    logger.info("Starting application initialization...")
    
    # Try to initialize database
    db_initialized = await safe_init_db()
    
    if not db_initialized:
        if ENVIRONMENT == "production":
            logger.error("Database initialization failed in production - starting in degraded mode")
            # In production, you might want to start anyway with limited functionality
        else:
            logger.critical("Database initialization failed in development")
            # In development, you can choose to fail fast or continue
            # Uncomment the next line if you want the app to fail in development
            # raise RuntimeError(f"Database initialization failed after {db_state.max_retries} attempts: {db_state.initialization_error}")
            logger.warning("Continuing startup without database connection")
    
    logger.info("Application startup completed")
    
    try:
        yield
    finally:
        logger.info("Shutting down application...")
        try:
            if db_state.is_connected:
                await close_db()
                logger.info("Database connections closed successfully")
        except Exception as e:
            logger.error(f"Error during database shutdown: {e}", exc_info=True)

# --- CORS Configuration ---
def get_cors_origins():
    """Get CORS origins based on environment."""
    if ENVIRONMENT == "production":
        # In production, specify your actual frontend domains
        return [
            "https://yourdomain.com",
            "https://www.yourdomain.com",
            # Add your production frontend URLs here
        ]
    else:
        # Development origins
        return [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]

# --- FastAPI Application Instance ---
app = FastAPI(
    title="Bookstore API with NeonDB",
    description="A production-ready FastAPI bookstore with full CRUD operations using NeonDB",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if ENVIRONMENT != "production" else None,
    debug=DEBUG,
)

# --- Custom Exception Handlers ---
@app.exception_handler(DatabaseInitializationError)
async def database_init_exception_handler(request: Request, exc: DatabaseInitializationError):
    """Handle database initialization errors with proper JSON response."""
    logger.error(f"Database initialization error: {exc.message}")
    
    return JSONResponse(
        status_code=503,
        content={
            "error": "Service Unavailable",
            "message": "Database service is currently unavailable. Please try again later.",
            "detail": exc.message if DEBUG else "Database initialization failed",
            "type": "database_initialization_error",
            "retry_count": db_state.retry_count
        },
        headers={"Retry-After": "30"}  # Suggest retry after 30 seconds
    )

# --- Apply Exception Handlers ---
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"]  # Expose custom headers if needed
)

# --- Custom Middleware ---
app.middleware("http")(add_process_time_header)

# --- Database Dependency ---
async def get_db_or_fail():
    """Dependency to ensure database is available."""
    if not db_state.is_connected:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Service Unavailable",
                "message": "Database service is currently unavailable",
                "reason": db_state.initialization_error or "Database not connected",
                "type": "database_unavailable",
                "retry_count": db_state.retry_count
            },
            headers={"Retry-After": "30"}
        )

# --- Health Check Endpoints ---
@app.get("/health", include_in_schema=False)
async def health_check():
    """Comprehensive health check including database status."""
    return {
        "status": "healthy" if db_state.is_connected else "degraded",
        "service": "bookstore-api",
        "database": {
            "connected": db_state.is_connected,
            "error": db_state.initialization_error if not db_state.is_connected else None,
            "retry_count": db_state.retry_count
        },
        "environment": ENVIRONMENT
    }

@app.get("/health/startup", include_in_schema=False)
async def startup_health_check():
    """Simple health check that doesn't depend on database."""
    return {"status": "healthy", "service": "bookstore-api"}

@app.get("/health/db", include_in_schema=False)
async def database_health_check():
    """Database-specific health check."""
    if db_state.is_connected:
        return {"status": "connected", "message": "Database is available"}
    else:
        return JSONResponse(
            status_code=503,
            content={
                "status": "disconnected",
                "message": "Database is not available",
                "error": db_state.initialization_error,
                "retry_count": db_state.retry_count
            }
        )

# --- Include Routers ---
app.include_router(root_router)
app.include_router(health_router)
app.include_router(books_router, prefix="/api/v1", tags=["books"])
app.include_router(files_router, prefix="/api/v1", tags=["files"])

# --- Startup Event Logger ---
@app.on_event("startup")
async def startup_event():
    """Log application startup information."""
    logger.info(f"Starting Bookstore API in {ENVIRONMENT} environment")
    logger.info(f"Debug mode: {DEBUG}")
    logger.info(f"Documentation available: {ENVIRONMENT != 'production'}")
    try:
        # Initialize database
        await ensure_db_initialized()
        
        # Run migrations
        await add_versioning_columns()
        
    except Exception as e:
        logging.error(f"Startup error: {e}")

# --- Manual Database Retry Endpoint (for development/debugging) ---
@app.post("/admin/retry-db", include_in_schema=False)
async def retry_database_connection():
    """Manually retry database connection (useful for debugging)."""
    if ENVIRONMENT == "production":
        raise HTTPException(status_code=404, detail="Not found")
    
    logger.info("Manual database retry requested")
    db_initialized = await safe_init_db()
    
    return {
        "success": db_initialized,
        "connected": db_state.is_connected,
        "error": db_state.initialization_error,
        "retry_count": db_state.retry_count
    }

# --- AWS Lambda Handler ---
handler = Mangum(app, lifespan="off")  # Disable lifespan for Lambda

# --- Local Development Entry Point ---
if __name__ == "__main__":
    import uvicorn
    
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["default"],
        },
    }
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=DEBUG,
        log_config=log_config if not DEBUG else None,
        access_log=True,
        reload_dirs=["./"] if DEBUG else None,
    )    