import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from database import ensure_db_initialized

logger = logging.getLogger(__name__)


class DatabaseTextCleaner:
    """Utility class for cleaning text before database insertion"""
    
    @staticmethod
    def clean_for_postgresql(text: Optional[str]) -> Optional[str]:
        """
        Clean text to be PostgreSQL-safe
        Removes null bytes and other problematic characters
        """
        if not text:
            return text
            
        try:
            # Remove null bytes (the main culprit)
            cleaned = text.replace('\x00', '')
            
            # Remove other control characters that can cause issues
            # Keep: tab (\t, \x09), newline (\n, \x0a), carriage return (\r, \x0d)
            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', cleaned)
            
            # Ensure valid UTF-8 by encoding/decoding
            cleaned = cleaned.encode('utf-8', errors='ignore').decode('utf-8')
            
            return cleaned
            
        except Exception as e:
            logger.warning(f"Error cleaning text for database: {e}")
            # Return empty string if cleaning fails
            return ""

    @staticmethod
    def validate_text_length(text: Optional[str], max_length: int = 1000000) -> Optional[str]:
        """
        Validate and truncate text if it's too long
        """
        if not text:
            return text
            
        if len(text) > max_length:
            logger.warning(f"Text content truncated from {len(text)} to {max_length} characters")
            return text[:max_length] + "...[truncated]"
            
        return text

    @staticmethod
    def clean_metadata_json(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Clean and serialize metadata to JSON string
        """
        if not metadata:
            return None
            
        try:
            # Recursively clean all string values in metadata
            cleaned_metadata = DatabaseTextCleaner._clean_dict_strings(metadata)
            metadata_json = json.dumps(cleaned_metadata)
            # Clean the final JSON string too
            return DatabaseTextCleaner.clean_for_postgresql(metadata_json)
        except Exception as e:
            logger.warning(f"Failed to serialize metadata: {e}")
            return None

    @staticmethod
    def _clean_dict_strings(obj: Any) -> Any:
        """Recursively clean string values in dictionaries and lists"""
        if isinstance(obj, dict):
            return {k: DatabaseTextCleaner._clean_dict_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [DatabaseTextCleaner._clean_dict_strings(item) for item in obj]
        elif isinstance(obj, str):
            return DatabaseTextCleaner.clean_for_postgresql(obj)
        else:
            return obj


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
        file_content: Optional[str] = None,
        score: Optional[float] = 0.0,
        folder_path: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        upload_ip: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Store file upload record in PostgreSQL database with text cleaning"""
        try:
            # Clean all text fields before database insertion
            cleaned_filename = DatabaseTextCleaner.clean_for_postgresql(original_filename)
            cleaned_content = DatabaseTextCleaner.clean_for_postgresql(file_content)
            cleaned_content = DatabaseTextCleaner.validate_text_length(cleaned_content)
            cleaned_folder_path = DatabaseTextCleaner.clean_for_postgresql(folder_path)
            cleaned_user_id = DatabaseTextCleaner.clean_for_postgresql(user_id)
            cleaned_upload_ip = DatabaseTextCleaner.clean_for_postgresql(upload_ip)
            
            # Validate required fields after cleaning
            if not cleaned_filename or not s3_key:
                raise ValueError("Filename and S3 key are required after cleaning")
            
            # Clean and serialize metadata
            metadata_json = DatabaseTextCleaner.clean_metadata_json(metadata)
            
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                record = await conn.fetchrow(
                    """
                    INSERT INTO file_uploads (
                        original_filename, s3_key, s3_url, file_size, content_type, file_content, score,
                        folder_path, user_id, metadata, upload_ip
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id, original_filename, s3_key, s3_url, file_size, 
                             content_type, folder_path, user_id, metadata, upload_ip,
                             upload_status, created_at, updated_at
                """,
                    cleaned_filename,
                    s3_key,  # S3 keys should be safe as they're generated by us
                    s3_url,  # URLs should be safe
                    file_size,
                    content_type,  # MIME types should be safe
                    cleaned_content,
                    score,
                    cleaned_folder_path,
                    cleaned_user_id,
                    metadata_json,
                    cleaned_upload_ip,
                )

                if record:
                    result = dict(record)
                    # Convert datetime objects to ISO format strings
                    for field in ["created_at", "updated_at"]:
                        if field in result and isinstance(result[field], datetime):
                            result[field] = result[field].isoformat()
                    
                    # Parse metadata back to dict if it exists
                    if result.get("metadata") and isinstance(result["metadata"], str):
                        try:
                            result["metadata"] = json.loads(result["metadata"])
                        except json.JSONDecodeError:
                            result["metadata"] = {}
                    
                    logger.info(f"Upload record created successfully: ID {result['id']}")
                    return result
                
                logger.error("Failed to create upload record: No record returned")
                return None

        except Exception as e:
            logger.error(f"Failed to create upload record: {e}", exc_info=True)
            
            # Check for specific PostgreSQL errors
            error_str = str(e).lower()
            if "invalid byte sequence" in error_str:
                logger.error("PostgreSQL encoding error detected. Check for null bytes or invalid UTF-8.")
            elif "value too long" in error_str:
                logger.error("Text content too long for database field.")
            elif "violates check constraint" in error_str:
                logger.error("Database constraint violation.")
            
            raise Exception(f"Database error: {str(e)}")

    async def get_upload_by_s3_key(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """Get upload record by S3 key"""
        try:
            if not s3_key or not s3_key.strip():
                logger.warning("Empty S3 key provided to get_upload_by_s3_key")
                return None
                
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                record = await conn.fetchrow(
                    """
                    SELECT * FROM file_uploads WHERE s3_key = $1
                """,
                    s3_key.strip(),
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
                            logger.warning(f"Invalid metadata JSON in record {record['id']}")
                            result["metadata"] = {}
                    return result
                return None

        except Exception as e:
            logger.error(f"Failed to get upload record for S3 key '{s3_key}': {e}")
            return None

    async def get_upload_record(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """Alias for get_upload_by_s3_key for compatibility"""
        return await self.get_upload_by_s3_key(s3_key)

    async def list_uploads(
        self,
        user_id: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List file uploads with optional filtering"""
        try:
            # Validate and clean input parameters
            if limit <= 0 or limit > 1000:
                limit = 100
            if offset < 0:
                offset = 0
                
            cleaned_user_id = DatabaseTextCleaner.clean_for_postgresql(user_id) if user_id else None
            cleaned_folder = DatabaseTextCleaner.clean_for_postgresql(folder) if folder else None
            
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                # Build base conditions
                base_conditions = []
                params = []
                param_count = 0
                
                if cleaned_user_id:
                    param_count += 1
                    base_conditions.append(f"user_id = ${param_count}")
                    params.append(cleaned_user_id)
                
                if cleaned_folder:
                    param_count += 1
                    base_conditions.append(f"folder_path = ${param_count}")
                    params.append(cleaned_folder)
                
                where_clause = " AND ".join(base_conditions) if base_conditions else "1=1"
                
                # Count query
                count_query = f"SELECT COUNT(*) FROM file_uploads WHERE {where_clause}"
                total_count = await conn.fetchval(count_query, *params)
                
                # Data query
                param_count += 1
                limit_param = f"${param_count}"
                param_count += 1
                offset_param = f"${param_count}"
                
                data_query = f"""
                    SELECT * FROM file_uploads 
                    WHERE {where_clause}
                    ORDER BY created_at DESC 
                    LIMIT {limit_param} OFFSET {offset_param}
                """
                params.extend([limit, offset])
                
                records = await conn.fetch(data_query, *params)

                # Process records
                processed_records = []
                for record in records:
                    try:
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
                                logger.warning(f"Invalid metadata JSON in record {record_dict.get('id', 'unknown')}")
                                record_dict["metadata"] = {}
                        processed_records.append(record_dict)
                    except Exception as e:
                        logger.warning(f"Error processing record: {e}")
                        continue

                logger.info(f"Retrieved {len(processed_records)} upload records (total: {total_count})")
                return {"records": processed_records, "total_count": total_count}

        except Exception as e:
            logger.error(f"Failed to list uploads: {e}", exc_info=True)
            raise Exception(f"Failed to retrieve upload records: {str(e)}")

    async def delete_upload_record(self, s3_key: str) -> bool:
        """Delete upload record from database"""
        try:
            if not s3_key or not s3_key.strip():
                logger.warning("Empty S3 key provided to delete_upload_record")
                return False
                
            # Ensure database connection is ready
            db_pool = await self.ensure_db_connection()

            async with db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM file_uploads WHERE s3_key = $1
                """,
                    s3_key.strip(),
                )
                
                deleted = result == "DELETE 1"
                if deleted:
                    logger.info(f"Successfully deleted upload record for S3 key: {s3_key}")
                else:
                    logger.warning(f"No record found to delete for S3 key: {s3_key}")
                    
                return deleted
                
        except Exception as e:
            logger.error(f"Failed to delete upload record for S3 key '{s3_key}': {e}")
            return False

    async def update_upload_status(
        self, 
        s3_key: str, 
        status: str, 
        error_message: Optional[str] = None
    ) -> bool:
        """Update upload status (useful for async processing)"""
        try:
            if not s3_key or not s3_key.strip():
                return False
                
            cleaned_status = DatabaseTextCleaner.clean_for_postgresql(status)
            cleaned_error = DatabaseTextCleaner.clean_for_postgresql(error_message)
            
            db_pool = await self.ensure_db_connection()
            
            async with db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE file_uploads 
                    SET upload_status = $1, error_message = $2, updated_at = NOW()
                    WHERE s3_key = $3
                    """,
                    cleaned_status,
                    cleaned_error,
                    s3_key.strip(),
                )
                
                return result == "UPDATE 1"
                
        except Exception as e:
            logger.error(f"Failed to update upload status: {e}")
            return False

    async def clean_existing_records(self) -> Dict[str, int]:
        """
        Utility method to clean existing records that might have problematic characters
        Returns count of cleaned records
        """
        try:
            db_pool = await self.ensure_db_connection()
            
            async with db_pool.acquire() as conn:
                # Clean null bytes and problematic characters from existing records
                result = await conn.execute(
                    """
                    UPDATE file_uploads 
                    SET 
                        file_content = REGEXP_REPLACE(COALESCE(file_content, ''), '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', 'g'),
                        original_filename = REGEXP_REPLACE(original_filename, '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', 'g'),
                        folder_path = REGEXP_REPLACE(COALESCE(folder_path, ''), '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', 'g'),
                        user_id = REGEXP_REPLACE(COALESCE(user_id, ''), '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', 'g'),
                        upload_ip = REGEXP_REPLACE(COALESCE(upload_ip, ''), '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', 'g'),
                        updated_at = NOW()
                    WHERE 
                        file_content ~ '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]' OR
                        original_filename ~ '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]' OR
                        folder_path ~ '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]' OR
                        user_id ~ '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]' OR
                        upload_ip ~ '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]'
                    """
                )
                
                # Extract the number of updated rows
                updated_count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
                
                logger.info(f"Cleaned {updated_count} existing records")
                return {"cleaned_records": updated_count}
                
        except Exception as e:
            logger.error(f"Failed to clean existing records: {e}")
            return {"error": str(e), "cleaned_records": 0}

    async def get_upload_stats(self) -> Dict[str, Any]:
        """Get upload statistics"""
        try:
            db_pool = await self.ensure_db_connection()
            
            async with db_pool.acquire() as conn:
                stats = await conn.fetchrow(
                    """
                    SELECT 
                        COUNT(*) as total_uploads,
                        COUNT(DISTINCT user_id) as unique_users,
                        SUM(file_size) as total_size_bytes,
                        AVG(score) as average_score,
                        COUNT(CASE WHEN upload_status = 'success' THEN 1 END) as successful_uploads,
                        COUNT(CASE WHEN upload_status = 'failed' THEN 1 END) as failed_uploads
                    FROM file_uploads
                    """
                )
                
                if stats:
                    result = dict(stats)
                    # Convert bytes to more readable format
                    if result['total_size_bytes']:
                        result['total_size_mb'] = round(result['total_size_bytes'] / (1024 * 1024), 2)
                    if result['average_score']:
                        result['average_score'] = round(float(result['average_score']), 2)
                    return result
                    
                return {}
                
        except Exception as e:
            logger.error(f"Failed to get upload stats: {e}")
            return {}


# Create global uploads service instance
uploads_service = UploadsService()