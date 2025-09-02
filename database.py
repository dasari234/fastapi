import asyncio
import logging

import asyncpg
from fastapi import HTTPException, status

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Global connection pool
db_pool = None

async def init_db():
    """Initialize DB connection pool and create tables"""
    global db_pool
    try:
        logger.info(f"Initializing DB connection to: {DATABASE_URL.split('@')[1].split('/')[0] if '@' in DATABASE_URL else 'Unknown'}")

        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
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
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS file_uploads (
                    id SERIAL PRIMARY KEY,
                    original_filename VARCHAR(255) NOT NULL,
                    s3_key VARCHAR(500) NOT NULL UNIQUE,
                    s3_url VARCHAR(1000) NOT NULL,
                    file_size BIGINT NOT NULL,
                    content_type VARCHAR(100) NOT NULL,
                    folder_path VARCHAR(255),
                    upload_status VARCHAR(20) DEFAULT 'success' CHECK (upload_status IN ('success', 'failed')),
                    user_id VARCHAR(100),
                    metadata JSONB,
                    upload_ip VARCHAR(45),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create indexes for file_uploads table
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_key ON file_uploads(s3_key);
                CREATE INDEX IF NOT EXISTS idx_file_uploads_user_id ON file_uploads(user_id);
                CREATE INDEX IF NOT EXISTS idx_file_uploads_created_at ON file_uploads(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_file_uploads_folder ON file_uploads(folder_path);
            """)

        logger.info("DB initialized successfully!")

    except Exception as e:
        logger.error(f"Failed to initialize DB: {e}")
        if "password authentication failed" in str(e):
            logger.error("Check your DB credentials in .env file")
        raise

async def close_db():
    """Close DB connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("DB connection closed")
        
async def get_db():
    """Dependency to get DB connection with robust error handling"""
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
       
async def get_db_connection():
    """Get a database connection, initializing pool if necessary"""
    global db_pool
    if db_pool is None:
        await init_db()
    return db_pool

async def ensure_db_initialized():
    """Ensure database is initialized before operations"""
    global db_pool
    if db_pool is None:
        logger.warning("Database not initialized. Initializing now...")
        await init_db()
    return db_pool

def get_db_pool():
    """Get the database pool instance"""
    return db_pool