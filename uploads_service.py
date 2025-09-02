import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from database import ensure_db_initialized

logger = logging.getLogger(__name__)


class UploadsService:
    
    async def ensure_db_connection(self):
        """Ensure database connection pool is initialized"""
        db_pool = await ensure_db_initialized()
        if db_pool is None:
            raise Exception("Database pool could not be initialized")
        return db_pool

    async def create_upload_record(
        self,
        original_filename: str,
        s3_key: str,
        s3_url: str,
        file_size: int,
        content_type: str,
        folder_path: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        upload_ip: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Store file upload record in PostgreSQL database"""
        try:
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                # Convert metadata to JSON string if it's a dict
                metadata_json = json.dumps(metadata) if metadata else None

                record = await conn.fetchrow(
                    """
                    INSERT INTO file_uploads (
                        original_filename, s3_key, s3_url, file_size, content_type,
                        folder_path, user_id, metadata, upload_ip
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id, original_filename, s3_key, s3_url, file_size, 
                             content_type, folder_path, user_id, metadata, upload_ip,
                             upload_status, created_at, updated_at
                """,
                    original_filename,
                    s3_key,
                    s3_url,
                    file_size,
                    content_type,
                    folder_path,
                    user_id,
                    metadata_json,
                    upload_ip,
                )

                if record:
                    result = dict(record)
                    # Convert datetime objects to ISO format strings
                    for field in ["created_at", "updated_at"]:
                        if field in result and isinstance(result[field], datetime):
                            result[field] = result[field].isoformat()
                    return result
                return None

        except Exception as e:
            logger.error(f"Failed to create upload record: {e}")
            raise Exception(f"Database error: {str(e)}")

    async def get_upload_by_s3_key(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """Get upload record by S3 key"""
        try:
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                record = await conn.fetchrow(
                    """
                    SELECT * FROM file_uploads WHERE s3_key = $1
                """,
                    s3_key,
                )

                if record:
                    result = dict(record)
                    # Convert datetime objects to ISO format strings
                    for field in ["created_at", "updated_at"]:
                        if field in result and isinstance(result[field], datetime):
                            result[field] = result[field].isoformat()
                    # Parse metadata JSON if it exists
                    if result.get("metadata") and isinstance(result["metadata"], str):
                        try:
                            result["metadata"] = json.loads(result["metadata"])
                        except json.JSONDecodeError:
                            result["metadata"] = None
                    return result
                return None

        except Exception as e:
            logger.error(f"Failed to get upload record: {e}")
            return None

    async def list_uploads(
        self,
        user_id: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List file uploads with optional filtering"""
        try:
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                # Build base conditions
                base_conditions = []
                params = []
                
                if user_id:
                    base_conditions.append("user_id = $1")
                    params.append(user_id)
                
                if folder:
                    base_conditions.append("folder_path = $2")
                    params.append(folder)
                
                where_clause = " AND ".join(base_conditions) if base_conditions else "1=1"
                
                # Count query
                count_query = f"SELECT COUNT(*) FROM file_uploads WHERE {where_clause}"
                total_count = await conn.fetchval(count_query, *params)
                
                # Data query
                data_query = f"""
                    SELECT * FROM file_uploads 
                    WHERE {where_clause}
                    ORDER BY created_at DESC 
                    LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
                """
                params.extend([limit, offset])
                
                records = await conn.fetch(data_query, *params)

                # Process records
                processed_records = []
                for record in records:
                    record_dict = dict(record)
                    # Convert datetime objects
                    for field in ["created_at", "updated_at"]:
                        if field in record_dict and isinstance(record_dict[field], datetime):
                            record_dict[field] = record_dict[field].isoformat()
                    # Parse metadata
                    if record_dict.get("metadata") and isinstance(record_dict["metadata"], str):
                        try:
                            record_dict["metadata"] = json.loads(record_dict["metadata"])
                        except json.JSONDecodeError:
                            record_dict["metadata"] = {}
                    processed_records.append(record_dict)

                return {"records": processed_records, "total_count": total_count}

        except Exception as e:
            logger.error(f"Failed to list uploads: {e}")
            raise

    async def delete_upload_record(self, s3_key: str) -> bool:
        """Delete upload record from database"""
        try:
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM file_uploads WHERE s3_key = $1
                """,
                    s3_key,
                )
                return result == "DELETE 1"
        except Exception as e:
            logger.error(f"Failed to delete upload record: {e}")
            return False


# Create global uploads service instance
uploads_service = UploadsService()