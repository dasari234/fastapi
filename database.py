import asyncio
import logging
import time
import weakref
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import asyncpg
from fastapi import HTTPException, status

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Global connection pool
db_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()
_initialization_in_progress = False

class DatabaseConfig:
    """Database configuration constants"""
    MIN_SIZE = 2
    MAX_SIZE = 20
    MAX_QUERIES = 50000
    MAX_INACTIVE_CONNECTION_LIFETIME = 300
    CONNECTION_TIMEOUT = 30
    COMMAND_TIMEOUT = 60
    HEALTH_CHECK_INTERVAL = 30
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 0.5
    
    @classmethod
    def get_pool_settings(cls) -> Dict[str, Any]:
        """Get pool configuration settings"""
        return {
            "min_size": cls.MIN_SIZE,
            "max_size": cls.MAX_SIZE,
            "max_queries": cls.MAX_QUERIES,
            "max_inactive_connection_lifetime": cls.MAX_INACTIVE_CONNECTION_LIFETIME,
            "timeout": cls.CONNECTION_TIMEOUT,
            "command_timeout": cls.COMMAND_TIMEOUT,
            "server_settings": {
                "application_name": "fastapi_file_service",
                "jit": "off",
                "timezone": "UTC"
            }
        }

class DatabaseHealthChecker:
    """Monitor database connection health"""
    
    def __init__(self):
        self.last_check = 0
        self.is_healthy = True
        self.consecutive_failures = 0
        
    async def check_health(self, pool: asyncpg.Pool) -> bool:
        """Check if database connection is healthy"""
        now = time.time()
        
        # Skip frequent checks
        if now - self.last_check < DatabaseConfig.HEALTH_CHECK_INTERVAL:
            return self.is_healthy
            
        try:
            async with pool.acquire(timeout=5) as conn:
                await conn.fetchval("SELECT 1", timeout=3)
                
            self.is_healthy = True
            self.consecutive_failures = 0
            self.last_check = now
            return True
            
        except Exception as e:
            self.consecutive_failures += 1
            self.is_healthy = False
            logger.warning(f"Database health check failed (attempt {self.consecutive_failures}): {e}")
            
            if self.consecutive_failures >= 3:
                logger.error("Database connection appears to be down after multiple health check failures")
                
            return False

# Global health checker instance
health_checker = DatabaseHealthChecker()

async def get_database_url_info() -> str:
    """Get safe database URL info for logging (without credentials)"""
    try:
        if '@' in DATABASE_URL and '/' in DATABASE_URL:
            # Extract host info safely
            parts = DATABASE_URL.split('@')
            if len(parts) > 1:
                host_part = parts[1].split('/')[0]
                return host_part
        return "Unknown host"
    except Exception:
        return "Unknown host"

async def init_db_without_table_check(force_recreate: bool = False) -> asyncpg.Pool:
    """Initialize DB connection pool without table checks to avoid recursion"""
    global db_pool, _initialization_in_progress
    
    async with _pool_lock:
        if db_pool and not force_recreate:
            return db_pool
        
        if _initialization_in_progress:
            while _initialization_in_progress:
                await asyncio.sleep(0.1)
            if db_pool:
                return db_pool
        
        _initialization_in_progress = True
        
        try:
            db_info = await get_database_url_info()
            logger.info(f"Initializing DB connection pool to: {db_info}")
            
            ssl_mode = "require"
            if "localhost" in DATABASE_URL or "127.0.0.1" in DATABASE_URL:
                ssl_mode = "prefer"
            
            pool_config = DatabaseConfig.get_pool_settings()
            pool_config["ssl"] = ssl_mode
            
            db_pool = await asyncpg.create_pool(DATABASE_URL, **pool_config)
            
            # Test the connection but skip table creation to avoid recursion
            async with db_pool.acquire(timeout=10) as conn:
                await conn.fetchval("SELECT version()")
            
            # Initial health check
            await health_checker.check_health(db_pool)
            
            logger.info("Database pool initialized successfully")
            return db_pool
            
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            if db_pool:
                return db_pool
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database initialization failed: {str(e)}"
            )
        finally:
            _initialization_in_progress = False
            
async def check_table_exists(table_name: str, conn: asyncpg.Connection = None) -> bool:
    """Check if a specific table exists without causing recursion"""
    try:
        if conn:
            # Use provided connection
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = $1
                )
            """, table_name)
            return exists
        else:
            # Get new connection without recursion
            pool = db_pool
            if pool is None:
                # Initialize without checking tables to avoid recursion
                pool = await init_db_without_table_check()
            async with pool.acquire() as temp_conn:
                exists = await temp_conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'public' AND table_name = $1
                    )
                """, table_name)
                return exists
    except Exception as e:
        logger.error(f"Error checking if table {table_name} exists: {e}")
        return False

async def emergency_create_missing_tables() -> Dict[str, bool]:
    """Emergency function to create missing tables"""
    try:
        pool = await init_db_without_table_check()
        async with pool.acquire() as conn:
            return await emergency_create_missing_tables_direct(conn)
    except Exception as e:
        logger.error(f"Emergency table creation failed: {e}")
        return {"error": str(e), "file_uploads_created": False}
    
async def create_database_tables(conn: asyncpg.Connection) -> None:
    """Create all required database tables and indexes"""
    try:
        logger.info("Creating database tables and indexes...")
        
        # Check if BOTH tables exist (more specific check)
        books_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'books'
            )
        """)
        
        file_uploads_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'file_uploads'
            )
        """)
        
        if books_exists and file_uploads_exists:
            logger.info("Both tables already exist, skipping creation")
            return
        
        logger.info(f"Books exists: {books_exists}, File_uploads exists: {file_uploads_exists}")
        
        # Create books table if it doesn't exist
        if not books_exists:
            await conn.execute("""
                CREATE TABLE books (
                    book_id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    genre VARCHAR(20) NOT NULL CHECK (genre IN ('fiction', 'non-fiction')),
                    price DECIMAL(10, 2) NOT NULL CHECK (price > 0),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info("Books table created")
            
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS file_history (
                id SERIAL PRIMARY KEY,
                file_upload_id INTEGER NOT NULL REFERENCES file_uploads(id) ON DELETE CASCADE,
                original_filename VARCHAR(255) NOT NULL,
                s3_key VARCHAR(500) NOT NULL,
                s3_url VARCHAR(1000) NOT NULL,
                file_size BIGINT NOT NULL,
                content_type VARCHAR(100) NOT NULL,
                file_content TEXT,
                score DECIMAL(5,2) DEFAULT 0.0,
                folder_path VARCHAR(255),
                user_id VARCHAR(100),
                metadata JSONB,
                upload_ip VARCHAR(45),
                version INTEGER NOT NULL,
                version_comment TEXT,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- Indexes for better performance
                INDEX idx_file_history_filename (original_filename),
                INDEX idx_file_history_user_id (user_id),
                INDEX idx_file_history_version (version)
            );
        """)

        # Create file_uploads table if it doesn't exist
        if not file_uploads_exists:
            await conn.execute("""
                CREATE TABLE file_uploads (
                    id SERIAL PRIMARY KEY,
                    original_filename VARCHAR(255) NOT NULL,
                    s3_key VARCHAR(500) NOT NULL UNIQUE,
                    s3_url VARCHAR(1000) NOT NULL,
                    file_size BIGINT NOT NULL CHECK (file_size >= 0),
                    content_type VARCHAR(100) NOT NULL,
                    folder_path VARCHAR(255),
                    file_content TEXT,
                    score DECIMAL(5,2) DEFAULT 0.0 CHECK (score >= 0 AND score <= 100),
                    upload_status VARCHAR(20) DEFAULT 'success' CHECK (upload_status IN ('success', 'failed', 'processing', 'error')),
                    error_message TEXT,
                    user_id VARCHAR(100),
                    metadata JSONB,
                    upload_ip VARCHAR(45),
                    -- Versioning columns
                    version INTEGER DEFAULT 1 CHECK (version >= 1),
                    is_current_version BOOLEAN DEFAULT TRUE,
                    previous_version_id INTEGER REFERENCES file_uploads(id),
                    version_comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    CONSTRAINT check_filename_clean CHECK (original_filename !~ '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]'),
                    CONSTRAINT check_no_empty_filename CHECK (LENGTH(TRIM(original_filename)) > 0),
                    CONSTRAINT check_s3_key_format CHECK (s3_key ~ '^[a-zA-Z0-9._/-]+$')
                );
            """)
            logger.info("File_uploads table created")

        # Create indexes (these will be created if they don't exist)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_books_genre ON books(genre);
            CREATE INDEX IF NOT EXISTS idx_books_price ON books(price);
            CREATE INDEX IF NOT EXISTS idx_books_created_at ON books(created_at DESC);
        """)

        # Create updated_at trigger function
        await conn.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        
        # Create triggers
        await conn.execute("""
            DROP TRIGGER IF EXISTS update_books_updated_at ON books;
            CREATE TRIGGER update_books_updated_at
                BEFORE UPDATE ON books
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)
        
        # Create indexes for file_uploads table
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_key ON file_uploads(s3_key);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_user_id ON file_uploads(user_id) WHERE user_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_file_uploads_created_at ON file_uploads(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_folder ON file_uploads(folder_path) WHERE folder_path IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_file_uploads_status ON file_uploads(upload_status);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_size ON file_uploads(file_size);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_content_type ON file_uploads(content_type);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_version ON file_uploads(original_filename, version);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_current_version ON file_uploads(is_current_version);
        """)
        
        # Create trigger for file_uploads table
        await conn.execute("""
            DROP TRIGGER IF EXISTS update_file_uploads_updated_at ON file_uploads;
            CREATE TRIGGER update_file_uploads_updated_at
                BEFORE UPDATE ON file_uploads
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)
        
        # Create a view for upload statistics
        await conn.execute("""
            CREATE OR REPLACE VIEW upload_stats AS
            SELECT 
                COUNT(*) as total_uploads,
                COUNT(DISTINCT user_id) as unique_users,
                SUM(file_size) as total_size_bytes,
                AVG(score) as average_score,
                COUNT(CASE WHEN upload_status = 'success' THEN 1 END) as successful_uploads,
                COUNT(CASE WHEN upload_status = 'failed' THEN 1 END) as failed_uploads,
                COUNT(CASE WHEN upload_status = 'processing' THEN 1 END) as processing_uploads,
                MAX(created_at) as last_upload_time,
                COUNT(CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN 1 END) as uploads_last_24h
            FROM file_uploads;
        """)
        
        logger.info("Database tables and indexes created successfully")
        
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")


async def add_versioning_columns() -> bool:
    """Add versioning columns to file_uploads table"""
    migration_sql = """
    -- Add versioning columns to file_uploads table
    ALTER TABLE file_uploads 
    ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_current_version BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS previous_version_id INTEGER REFERENCES file_uploads(id),
    ADD COLUMN IF NOT EXISTS version_comment TEXT;

    -- Create index for better performance
    CREATE INDEX IF NOT EXISTS idx_file_uploads_version ON file_uploads(original_filename, version);
    CREATE INDEX IF NOT EXISTS idx_file_uploads_current_version ON file_uploads(is_current_version);
    
    -- Update existing records to have version 1 and be current
    UPDATE file_uploads SET version = 1, is_current_version = TRUE 
    WHERE version IS NULL OR is_current_version IS NULL;
    """
    
    return await run_database_migration(
        migration_sql, 
        "Add versioning columns to file_uploads table"
    )

async def force_recreate_tables() -> Dict[str, bool]:
    """Force recreation of all tables (DANGEROUS - will lose data!)"""
    try:
        pool = await ensure_db_initialized()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Drop tables if they exist
                await conn.execute("""
                    DROP TABLE IF EXISTS file_uploads CASCADE;
                    DROP TABLE IF EXISTS books CASCADE;
                    DROP VIEW IF EXISTS upload_stats;
                """)
                
                # Recreate tables
                await create_database_tables(conn)
                
                return {"success": True, "message": "Tables force-recreated"}
                
    except Exception as e:
        logger.error(f"Force recreate tables failed: {e}")
        return {"success": False, "error": str(e)}

async def init_db(force_recreate: bool = False) -> asyncpg.Pool:
    """Initialize DB connection pool and create tables"""
    global db_pool, _initialization_in_progress
    
    async with _pool_lock:
        if db_pool and not force_recreate:
            if await health_checker.check_health(db_pool):
                return db_pool
            else:
                logger.warning("Existing pool is unhealthy, recreating...")
                await close_db()
        
        if _initialization_in_progress:
            # Wait for ongoing initialization
            while _initialization_in_progress:
                await asyncio.sleep(0.1)
            if db_pool:
                return db_pool
        
        _initialization_in_progress = True
        
        try:
            db_info = await get_database_url_info()
            logger.info(f"Initializing DB connection pool to: {db_info}")
            
            # Determine SSL requirements
            ssl_mode = "require"
            if "localhost" in DATABASE_URL or "127.0.0.1" in DATABASE_URL:
                ssl_mode = "prefer"
            
            pool_config = DatabaseConfig.get_pool_settings()
            pool_config["ssl"] = ssl_mode
            
            db_pool = await asyncpg.create_pool(DATABASE_URL, **pool_config)
            
            # Test the connection and create tables
            async with db_pool.acquire(timeout=10) as conn:
                await conn.fetchval("SELECT version()")
                await create_database_tables(conn)
            
            # Initial health check
            await health_checker.check_health(db_pool)
            
            logger.info(f"Database pool initialized successfully with {DatabaseConfig.MIN_SIZE}-{DatabaseConfig.MAX_SIZE} connections")
            return db_pool
            
        except asyncpg.InvalidAuthorizationSpecificationError:
            logger.error("Database authentication failed. Check your credentials in the .env file")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database authentication failed"
            )
        except asyncpg.InvalidCatalogNameError as e:
            logger.error(f"Database does not exist: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not found"
            )
        except asyncpg.ConnectionDoesNotExistError as e:
            logger.error(f"Cannot connect to database server: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database server unavailable"
            )
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database initialization failed: {str(e)}"
            )
        finally:
            _initialization_in_progress = False

async def close_db() -> None:
    """Close DB connection pool gracefully"""
    global db_pool
    
    async with _pool_lock:
        if db_pool:
            try:
                await db_pool.close()
                logger.info("Database connection pool closed successfully")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}")
            finally:
                db_pool = None

@asynccontextmanager
async def get_db_connection(timeout: float = 10.0):
    """
    Context manager for getting database connections with automatic cleanup
    Usage: async with get_db_connection() as conn: ...
    """
    if not db_pool:
        await ensure_db_initialized()
    
    connection = None
    try:
        connection = await db_pool.acquire(timeout=timeout)
        yield connection
    except asyncio.TimeoutError:
        logger.error("Database connection timeout")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection timeout"
        )
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed"
        )
    finally:
        if connection:
            try:
                await db_pool.release(connection)
            except Exception as e:
                logger.error(f"Error releasing database connection: {e}")

async def get_db():
    """FastAPI dependency to get DB connection with robust error handling"""
    if not db_pool:
        try:
            await init_db()
        except Exception as e:
            logger.error(f"Database pool initialization failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service unavailable",
            )

    for attempt in range(DatabaseConfig.MAX_RETRIES):
        try:
            async with db_pool.acquire(timeout=DatabaseConfig.CONNECTION_TIMEOUT) as conn:
                # Quick health check
                await conn.fetchval("SELECT 1", timeout=5)
                yield conn
                return
        except asyncio.TimeoutError:
            logger.warning(f"Database connection timeout (attempt {attempt + 1})")
        except Exception as e:
            logger.warning(f"Database connection failed (attempt {attempt + 1}): {e}")
            
        if attempt < DatabaseConfig.MAX_RETRIES - 1:
            wait_time = DatabaseConfig.RETRY_DELAY_BASE * (2 ** attempt)
            await asyncio.sleep(wait_time)
    
    logger.error(f"Database connection failed after {DatabaseConfig.MAX_RETRIES} attempts")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database connection unavailable",
    )

async def emergency_create_missing_tables_direct(conn: asyncpg.Connection) -> Dict[str, bool]:
    """Emergency function to create missing tables using provided connection"""
    try:
        # Check if file_uploads table exists
        file_uploads_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'file_uploads'
            )
        """)
        
        if not file_uploads_exists:
            logger.warning("file_uploads table missing, creating emergency table...")
            
            # Create basic file_uploads table without constraints first
            await conn.execute("""
                CREATE TABLE file_uploads (
                    id SERIAL PRIMARY KEY,
                    original_filename VARCHAR(255),
                    s3_key VARCHAR(500),
                    s3_url VARCHAR(1000),
                    file_size BIGINT,
                    content_type VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Add other columns gradually
            await conn.execute("""
                ALTER TABLE file_uploads 
                ADD COLUMN folder_path VARCHAR(255),
                ADD COLUMN file_content TEXT,
                ADD COLUMN score DECIMAL(5,2) DEFAULT 0.0,
                ADD COLUMN upload_status VARCHAR(20) DEFAULT 'success',
                ADD COLUMN error_message TEXT,
                ADD COLUMN user_id VARCHAR(100),
                ADD COLUMN metadata JSONB,
                ADD COLUMN upload_ip VARCHAR(45),
                ADD COLUMN version INTEGER DEFAULT 1,
                ADD COLUMN is_current_version BOOLEAN DEFAULT TRUE,
                ADD COLUMN previous_version_id INTEGER,
                ADD COLUMN version_comment TEXT;
            """)
            
            # Add constraints later
            await conn.execute("""
                ALTER TABLE file_uploads 
                ALTER COLUMN original_filename SET NOT NULL,
                ALTER COLUMN s3_key SET NOT NULL,
                ALTER COLUMN s3_url SET NOT NULL,
                ALTER COLUMN file_size SET NOT NULL,
                ALTER COLUMN content_type SET NOT NULL;
                
                ALTER TABLE file_uploads ADD CONSTRAINT file_uploads_s3_key_unique UNIQUE (s3_key);
            """)
            
            logger.info("Emergency file_uploads table created successfully")
            return {"file_uploads_created": True}
        else:
            logger.info("file_uploads table already exists")
            return {"file_uploads_created": False}
            
    except Exception as e:
        logger.error(f"Emergency table creation failed: {e}")
        return {"error": str(e), "file_uploads_created": False}

async def ensure_db_initialized() -> asyncpg.Pool:
    """Ensure database is initialized before operations"""
    global db_pool
    
    if db_pool is None:
        logger.info("Database not initialized. Initializing now...")
        await init_db()
    elif not await health_checker.check_health(db_pool):
        logger.warning("Database pool is unhealthy. Reinitializing...")
        await init_db(force_recreate=True)
    
    # Check if file_uploads table exists using a direct connection to avoid recursion
    try:
        async with db_pool.acquire() as conn:
            file_uploads_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = 'file_uploads'
                )
            """)
            
            if not file_uploads_exists:
                logger.warning("file_uploads table missing after initialization, creating emergency tables...")
                # Use direct connection for emergency creation
                await emergency_create_missing_tables_direct(conn)
    
    except Exception as e:
        logger.error(f"Error checking table existence in ensure_db_initialized: {e}")
    
    return db_pool

def get_db_pool() -> Optional[asyncpg.Pool]:
    """Get the database pool instance"""
    return db_pool

async def execute_with_retry(query: str, *args, max_retries: int = 3) -> Any:
    """
    Execute a database query with automatic retry on connection failures
    """
    pool = await ensure_db_initialized()
    
    for attempt in range(max_retries):
        try:
            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)
        except (asyncpg.ConnectionDoesNotExistError, asyncpg.InterfaceError) as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Database query failed (attempt {attempt + 1}): {e}")
            await asyncio.sleep(DatabaseConfig.RETRY_DELAY_BASE * (attempt + 1))
    
async def get_database_stats() -> Dict[str, Any]:
    """Get database connection pool statistics"""
    if not db_pool:
        return {"status": "not_initialized"}
    
    try:
        return {
            "status": "healthy" if health_checker.is_healthy else "unhealthy",
            "size": db_pool.get_size(),
            "min_size": db_pool.get_min_size(),
            "max_size": db_pool.get_max_size(),
            "idle_size": db_pool.get_idle_size(),
            "consecutive_failures": health_checker.consecutive_failures,
            "last_health_check": health_checker.last_check
        }
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return {"status": "error", "error": str(e)}

async def run_database_migration(migration_sql: str, description: str = "Migration") -> bool:
    """
    Run a database migration safely
    """
    try:
        pool = await ensure_db_initialized()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(migration_sql)
        
        logger.info(f"Database migration completed successfully: {description}")
        return True
        
    except Exception as e:
        logger.error(f"Database migration failed: {description} - {e}")
        return False

async def check_tables_exist() -> Dict[str, bool]:
    """Check if required tables exist in the database"""
    try:
        books_exists = await check_table_exists("books")
        file_uploads_exists = await check_table_exists("file_uploads")
        
        return {
            'books': books_exists,
            'file_uploads': file_uploads_exists,
            'all_tables_exist': books_exists and file_uploads_exists
        }
            
    except Exception as e:
        logger.error(f"Error checking tables: {e}")
        return {'error': str(e)}

# Cleanup function for graceful shutdown
async def cleanup_database():
    """Cleanup database connections on application shutdown"""
    try:
        await close_db()
    except Exception as e:
        logger.error(f"Error during database cleanup: {e}")

# Weak reference cleanup for connection tracking
_active_connections = weakref.WeakSet()