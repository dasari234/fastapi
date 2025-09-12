from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.files import router as files_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.root import router as root_router
from app.api.v1.routes.users import router as users_router
from app.config import DEBUG, ENVIRONMENT, VERSION
from app.database import close_db, init_db
from app.middleware.cors import setup_cors
from app.redis.base_config import close_redis_pool, init_redis_pool
from app.utils.exception_handling import global_exception_handler
from app.utils.logging_config import setup_logging
from app.utils.logging_request import log_requests_middleware

# --- Setup logging ---
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting FastAPI application...")
    logger.info("Environment: {}", ENVIRONMENT)
    logger.info("Version: {}", VERSION)
    
     # Initialize database
    try:
        await init_db()
        logger.success("Database initialized successfully")
    except Exception as e:
        logger.critical("Failed to initialize database: {}", e)
        raise

    # Initialize Redis (but don't crash if it fails)
    try:
        redis_success = await init_redis_pool()
        if redis_success:
            logger.success("Redis initialized successfully")
        else:
            logger.warning("Redis initialization failed - running without Redis caching")
    except Exception as e:
        logger.warning("Redis initialization failed with exception: {} - running without Redis", e)

    yield

    # Shutdown
    logger.info("Shutting down FastAPI application...")   
    try:
        await close_db()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error("Error closing database connection: {}", e)
        
    try:
        await close_redis_pool()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.error("Error closing Redis connection: {}", e)


app = FastAPI(
    title="Bookstore API",
    description="A RESTful API for managing books and users with NeonDB",
    version=VERSION,
    debug=DEBUG,
    lifespan=lifespan,
)

#---Setup CORS---
setup_cors(app)

# --- Include routers ---
app.include_router(root_router)
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")

# --- Add middleware ---
app.middleware("http")(log_requests_middleware)

# --- Add exception handler ---
app.exception_handler(Exception)(global_exception_handler)

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Uvicorn server...")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=DEBUG,
        log_level="error",
        access_log=False,
    )
