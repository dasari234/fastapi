import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Literal, Optional
from uuid import uuid4

import asyncpg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel, Field, field_validator

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
        if os.getenv("ENVIRONMENT") == "production"
        else logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# NeonDB configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable is required")
    raise ValueError("DATABASE_URL environment variable is required")

# Convert postgresql:// to postgres:// for asyncpg compatibility
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://")

# Global connection pool
db_pool = None


# Request/Response Models
class Book(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="The Great Gatsby")
    genre: Literal["fiction", "non-fiction"] = Field(..., example="fiction")
    price: float = Field(
        ..., gt=0, description="Price must be greater than 0", example=12.99
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        """Validate that name is not empty or whitespace only"""
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        return v.strip()


class BookUpdate(BaseModel):
    name: Optional[str] = Field(
        None, min_length=1, max_length=255, example="Updated Book Name"
    )
    genre: Optional[Literal["fiction", "non-fiction"]] = Field(None, example="fiction")
    price: Optional[float] = Field(
        None, gt=0, description="Price must be greater than 0", example=15.99
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: Optional[str]) -> Optional[str]:
        """Validate that name is not empty or whitespace only"""
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        return v.strip() if v else v


class BookResponse(BaseModel):
    book_id: str
    name: str
    genre: str
    price: float
    created_at: str
    updated_at: str


class HealthResponse(BaseModel):
    status: str
    database: str
    connection: str
    database_name: str
    postgresql_version: str
    environment: str
    response_time_ms: float


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    status_code: int


class SuccessResponse(BaseModel):
    message: str
    status_code: int
    data: Optional[dict] = None


# Database connection management
async def init_db():
    """Initialize NeonDB connection pool and create tables"""
    global db_pool
    try:
        logger.info(
            f"Initializing NeonDB connection to: {DATABASE_URL.split('@')[1].split('/')[0] if '@' in DATABASE_URL else 'Unknown'}"
        )

        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10 if os.getenv("ENVIRONMENT") == "production" else 3,
            max_queries=50000,
            max_inactive_connection_lifetime=300,
            timeout=30,
            command_timeout=60,
            server_settings={"application_name": "fastapi_bookstore", "jit": "off"},
            ssl="require",
        )

        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    book_id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    genre VARCHAR(20) NOT NULL CHECK (genre IN ('fiction', 'non-fiction')),
                    price DECIMAL(10, 2) NOT NULL CHECK (price > 0),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_genre ON books(genre);
                CREATE INDEX IF NOT EXISTS idx_books_price ON books(price);
                CREATE INDEX IF NOT EXISTS idx_books_created_at ON books(created_at DESC);
            """)

            await conn.execute("""
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ language 'plpgsql';
                
                DROP TRIGGER IF EXISTS update_books_updated_at ON books;
                CREATE TRIGGER update_books_updated_at
                    BEFORE UPDATE ON books
                    FOR EACH ROW
                    EXECUTE FUNCTION update_updated_at_column();
            """)

        logger.info("✅ NeonDB initialized successfully!")

    except Exception as e:
        logger.error(f"❌ Failed to initialize NeonDB: {e}")
        if "password authentication failed" in str(e):
            logger.error("💡 Check your NeonDB credentials in .env file")
        raise


async def close_db():
    """Close NeonDB connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("🔌 NeonDB connection closed")


async def get_db():
    """Dependency to get NeonDB connection with robust error handling"""
    if not db_pool:
        try:
            await init_db()
        except Exception as e:
            logger.error(f"Database pool initialization failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service unavailable",
            )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with db_pool.acquire(timeout=10) as conn:
                await conn.fetchval("SELECT 1", timeout=5)
                yield conn
                return
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(
                    f"Database connection failed after {max_retries} attempts: {e}"
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database connection unavailable",
                )
            await asyncio.sleep(0.5 * (attempt + 1))


# Lifespan management for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_db()
    except Exception as e:
        logger.critical(f"Application failed to start: {e}")
        raise
    yield
    # Shutdown
    await close_db()


# Custom exception handlers
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder(
            {
                "error": "Validation Error",
                "detail": exc.errors(),
                "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            }
        ),
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder({"error": exc.detail, "status_code": exc.status_code}),
    )


async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
        },
    )


# FastAPI Application
app = FastAPI(
    title="Bookstore API with NeonDB",
    description="A production-ready FastAPI bookstore with full CRUD operations using NeonDB",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if os.getenv("ENVIRONMENT") != "production" else None,
    redoc_url="/redoc" if os.getenv("ENVIRONMENT") != "production" else None,
    openapi_url="/openapi.json" if os.getenv("ENVIRONMENT") != "production" else None,
)

# Add exception handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

handler = Mangum(app)


# Middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    logger.info(
        f"{request.method} {request.url.path} - {response.status_code} - {process_time:.2f}ms"
    )
    return response


# API Endpoints
@app.get(
    "/",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    tags=["Root"],
    summary="API Root",
    responses={200: {"description": "Welcome message", "model": SuccessResponse}},
)
async def root():
    return SuccessResponse(
        message="Welcome to my NeonDB-powered bookstore app! 🚀",
        status_code=status.HTTP_200_OK,
        data={
            "database": "NeonDB (Serverless PostgreSQL)",
            "features": ["CRUD Operations", "Connection Pooling", "Auto-scaling"],
            "environment": os.getenv("ENVIRONMENT", "production"),
            "version": "2.0.0",
        },
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["Health"],
    summary="Health Check",
    responses={
        200: {"description": "Service is healthy", "model": HealthResponse},
        503: {"description": "Service unavailable", "model": ErrorResponse},
    },
)
async def health_check(conn: asyncpg.Connection = Depends(get_db)):
    """Health check endpoint for NeonDB"""
    start_time = time.time()
    try:
        await conn.fetchval("SELECT 1")
        version_info = await conn.fetchval("SELECT version()")
        db_name = await conn.fetchval("SELECT current_database()")
        response_time = (time.time() - start_time) * 1000

        return HealthResponse(
            status="healthy",
            database="NeonDB",
            connection="active",
            database_name=db_name,
            postgresql_version=version_info.split()[1] if version_info else "unknown",
            environment=os.getenv("ENVIRONMENT", "production"),
            response_time_ms=response_time,
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database health check failed",
        )


@app.post(
    "/books",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Books"],
    summary="Create a new book",
    responses={
        201: {"description": "Book created successfully", "model": BookResponse},
        400: {"description": "Invalid input", "model": ErrorResponse},
        409: {"description": "Book already exists", "model": ErrorResponse},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def create_book(book: Book, conn: asyncpg.Connection = Depends(get_db)):
    """Create a new book in the database"""
    book_id = uuid4().hex

    try:
        await conn.execute(
            """
            INSERT INTO books (book_id, name, genre, price)
            VALUES ($1, $2, $3, $4)
        """,
            book_id,
            book.name,
            book.genre,
            book.price,
        )

        row = await conn.fetchrow(
            """
            SELECT book_id, name, genre, price, created_at, updated_at 
            FROM books WHERE book_id = $1
        """,
            book_id,
        )

        logger.info(f"Book created: {book_id} - {book.name}")
        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    except asyncpg.UniqueViolationError:
        logger.warning(f"Book creation failed - duplicate ID: {book_id}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book with this ID already exists",
        )
    except Exception as e:
        logger.error(f"Book creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create book",
        )


@app.get(
    "/books",
    response_model=List[BookResponse],
    status_code=status.HTTP_200_OK,
    tags=["Books"],
    summary="Get all books",
    responses={
        200: {
            "description": "List of books retrieved successfully",
            "model": List[BookResponse],
        },
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def list_books(
    genre: Optional[Literal["fiction", "non-fiction"]] = None,
    limit: int = 100,
    offset: int = 0,
    conn: asyncpg.Connection = Depends(get_db),
):
    """Get all books with optional filtering and pagination"""
    try:
        if genre:
            rows = await conn.fetch(
                """
                SELECT book_id, name, genre, price, created_at, updated_at 
                FROM books WHERE genre = $1 
                ORDER BY created_at DESC LIMIT $2 OFFSET $3
            """,
                genre,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT book_id, name, genre, price, created_at, updated_at 
                FROM books ORDER BY created_at DESC LIMIT $1 OFFSET $2
            """,
                limit,
                offset,
            )

        return [
            BookResponse(
                book_id=row["book_id"],
                name=row["name"],
                genre=row["genre"],
                price=float(row["price"]),
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
            )
            for row in rows
        ]

    except Exception as e:
        logger.error(f"Failed to fetch books: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch books",
        )


@app.get(
    "/books/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
    tags=["Books"],
    summary="Get a book by ID",
    responses={
        200: {"description": "Book retrieved successfully", "model": BookResponse},
        404: {"description": "Book not found", "model": ErrorResponse},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def get_book_by_id(book_id: str, conn: asyncpg.Connection = Depends(get_db)):
    """Get a specific book by ID"""
    try:
        row = await conn.fetchrow(
            """
            SELECT book_id, name, genre, price, created_at, updated_at 
            FROM books WHERE book_id = $1
        """,
            book_id,
        )

        if not row:
            logger.warning(f"Book not found: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch book",
        )


@app.put(
    "/books/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
    tags=["Books"],
    summary="Update a book",
    responses={
        200: {"description": "Book updated successfully", "model": BookResponse},
        400: {"description": "Invalid input", "model": ErrorResponse},
        404: {"description": "Book not found", "model": ErrorResponse},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def update_book(
    book_id: str, book_update: BookUpdate, conn: asyncpg.Connection = Depends(get_db)
):
    """Update a specific book"""
    try:
        existing = await conn.fetchrow(
            "SELECT 1 FROM books WHERE book_id = $1", book_id
        )
        if not existing:
            logger.warning(f"Book not found for update: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        update_fields = []
        values = []
        param_count = 1

        if book_update.name is not None:
            update_fields.append(f"name = ${param_count}")
            values.append(book_update.name)
            param_count += 1

        if book_update.genre is not None:
            update_fields.append(f"genre = ${param_count}")
            values.append(book_update.genre)
            param_count += 1

        if book_update.price is not None:
            update_fields.append(f"price = ${param_count}")
            values.append(book_update.price)
            param_count += 1

        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update",
            )

        values.append(book_id)

        query = f"""
            UPDATE books SET {", ".join(update_fields)}
            WHERE book_id = ${param_count}
            RETURNING book_id, name, genre, price, created_at, updated_at
        """

        row = await conn.fetchrow(query, *values)
        logger.info(f"Book updated: {book_id}")

        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update book",
        )


@app.delete(
    "/books/{book_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    tags=["Books"],
    summary="Delete a book",
    responses={
        200: {"description": "Book deleted successfully", "model": SuccessResponse},
        404: {"description": "Book not found", "model": ErrorResponse},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def delete_book(book_id: str, conn: asyncpg.Connection = Depends(get_db)):
    """Delete a specific book"""
    try:
        result = await conn.execute("DELETE FROM books WHERE book_id = $1", book_id)

        if result == "DELETE 0":
            logger.warning(f"Book not found for deletion: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        logger.info(f"Book deleted: {book_id}")
        return SuccessResponse(
            message=f"Book with id {book_id} deleted successfully",
            status_code=status.HTTP_200_OK,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete book",
        )


@app.get(
    "/random-book",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
    tags=["Books"],
    summary="Get a random book",
    responses={
        200: {
            "description": "Random book retrieved successfully",
            "model": BookResponse,
        },
        404: {"description": "No books found", "model": ErrorResponse},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def get_random_book(conn: asyncpg.Connection = Depends(get_db)):
    """Get a random book from the database"""
    try:
        row = await conn.fetchrow("""
            SELECT book_id, name, genre, price, created_at, updated_at 
            FROM books ORDER BY RANDOM() LIMIT 1
        """)

        if not row:
            logger.warning("No books found for random selection")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No books found in database",
            )

        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    except Exception as e:
        logger.error(f"Failed to fetch random book: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch random book",
        )


@app.get(
    "/books/stats/summary",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    tags=["Statistics"],
    summary="Get books statistics",
    responses={
        200: {"description": "Statistics retrieved successfully"},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def get_books_stats(conn: asyncpg.Connection = Depends(get_db)):
    """Get statistics about books in the database"""
    try:
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_books,
                COUNT(CASE WHEN genre = 'fiction' THEN 1 END) as fiction_count,
                COUNT(CASE WHEN genre = 'non-fiction' THEN 1 END) as non_fiction_count,
                AVG(price) as average_price,
                MIN(price) as min_price,
                MAX(price) as max_price
            FROM books
        """)

        return {
            "total_books": stats["total_books"],
            "fiction_count": stats["fiction_count"],
            "non_fiction_count": stats["non_fiction_count"],
            "average_price": float(stats["average_price"])
            if stats["average_price"]
            else 0,
            "min_price": float(stats["min_price"]) if stats["min_price"] else 0,
            "max_price": float(stats["max_price"]) if stats["max_price"] else 0,
        }

    except Exception as e:
        logger.error(f"Failed to fetch statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch statistics",
        )


# Legacy endpoint for backwards compatibility
@app.post(
    "/add-book",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Legacy"],
    summary="Legacy endpoint to add a book",
    responses={
        201: {"description": "Book created successfully", "model": BookResponse},
        400: {"description": "Invalid input", "model": ErrorResponse},
        503: {"description": "Database unavailable", "model": ErrorResponse},
    },
)
async def add_book_legacy(book: Book, conn: asyncpg.Connection = Depends(get_db)):
    """Legacy endpoint - use POST /books instead"""
    return await create_book(book, conn)
