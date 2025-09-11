from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from api.v1.routes.auth import router as auth_router
from api.v1.routes.files import router as files_router
from api.v1.routes.health import router as health_router
from api.v1.routes.root import router as root_router
from api.v1.routes.users import router as users_router
from config import DEBUG, ENVIRONMENT, VERSION
from database import close_db, init_db
from middleware.cors import setup_cors
from utils.exception_handling import global_exception_handler
from utils.logging_config import setup_logging
from utils.logging_request import log_requests_middleware

# Setup logging
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

    yield

    # Shutdown
    logger.info("Shutting down FastAPI application...")
    try:
        await close_db()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error("Error closing database connection: {}", e)


app = FastAPI(
    title="Bookstore API",
    description="A RESTful API for managing books and users with NeonDB",
    version=VERSION,
    debug=DEBUG,
    lifespan=lifespan,
)

# Setup CORS
setup_cors(app)

# Include routers
app.include_router(root_router)
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
app.include_router(users_router, prefix="/api/v1", tags=["users"])
app.include_router(files_router, prefix="/api/v1", tags=["files"])

# Add middleware
app.middleware("http")(log_requests_middleware)

# Add exception handler
app.exception_handler(Exception)(global_exception_handler)

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Uvicorn server...")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=DEBUG,
        log_level="error",
        access_log=False,
    )
