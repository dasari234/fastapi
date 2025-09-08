import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import DEBUG, ENVIRONMENT, VERSION
from middleware.cors import setup_cors
from database.database import close_db, init_db
from routes.auth import router as auth_router
from routes.files import router as files_router
from routes.health import router as health_router
from routes.root import router as root_router
from routes.users import router as users_router

# Configure logging
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting FastAPI application...")
    logger.info(f"Environment: {ENVIRONMENT}")
    logger.info(f"Version: {VERSION}")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down FastAPI application...")
    await close_db()
    logger.info("Database connection closed")
    

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

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=DEBUG,
        log_level="info" if not DEBUG else "debug",
    )
    
    