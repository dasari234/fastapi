
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from config import DEBUG, ENVIRONMENT
from database import close_db, init_db
from exceptions import (generic_exception_handler, http_exception_handler,
                        validation_exception_handler)
from middleware import add_process_time_header
from routes.books import router as books_router
from routes.files import router as files_router
from routes.health import router as health_router
from routes.root import router as root_router

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log") if ENVIRONMENT == "production" else logging.StreamHandler(),
    ],
)


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    Initializes and closes the database connection.
    """
    try:
        await init_db()
    except Exception as e:
        logging.critical(f"Application failed to start: {e}")
        raise
    yield
    await close_db()


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



# --- Exception Handlers ---
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# --- CORS Configuration ---
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Custom Middleware ---
app.middleware("http")(add_process_time_header)

# --- Routers ---
app.include_router(root_router)
app.include_router(health_router)
app.include_router(books_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")

# --- AWS Lambda Handler ---
handler = Mangum(app)

# --- Local Development Entry Point ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=DEBUG
    )