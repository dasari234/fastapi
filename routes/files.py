import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import chardet
from fastapi import (APIRouter, File, Form, HTTPException, Query, Request,
                     UploadFile, status)
from fastapi.concurrency import run_in_threadpool

from config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from s3_service import s3_service
from schemas import (DeleteFileResponse, FileUploadListResponse,
                     MultipleFileUploadResponse, UploadedFileInfo, UploadError)
from uploads_service import uploads_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Files"], prefix="/files")

# Constants
MAX_CONTENT_LENGTH_FOR_SCORING = 1024 * 1024  # 1MB limit for text content analysis
CHUNK_SIZE = 8192  # 8KB chunks for memory-efficient reading

class FileValidator:
    """File validation utility class"""
    
    @staticmethod
    def validate_file_basic(file: UploadFile) -> None:
        """Basic file validation (size and type)"""
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required"
            )
            
        # Check file size
        if file.size and file.size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size too large. Maximum allowed: {MAX_FILE_SIZE // (1024 * 1024)}MB",
            )

        # Check file extension
        file_extension = Path(file.filename).suffix.lower().lstrip('.')
        if not file_extension:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must have an extension"
            )
            
        allowed_extensions = []
        for extensions in ALLOWED_EXTENSIONS.values():
            allowed_extensions.extend(extensions)

        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File type '{file_extension}' not allowed. Allowed types: {', '.join(allowed_extensions)}",
            )

    @staticmethod
    def validate_filename(filename: str) -> str:
        """Sanitize and validate filename"""
        if not filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename cannot be empty"
            )
        
        # Remove/replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        sanitized = ''.join(c if c not in invalid_chars else '_' for c in filename)
        
        # Ensure filename isn't too long
        if len(sanitized) > 255:
            sanitized = sanitized[:255]
            
        return sanitized

class ContentProcessor:
    """Content processing utility class"""
    
    @staticmethod
    async def read_file_content_safely(file: UploadFile) -> tuple[bytes, str, float]:
        """
        Safely read file content with encoding detection and scoring
        Returns: (raw_content, text_content, score)
        """
        try:
            # Read raw content
            raw_content = await file.read()
            
            # Limit content size for text processing to avoid memory issues
            content_for_analysis = raw_content[:MAX_CONTENT_LENGTH_FOR_SCORING]
            
            # Detect encoding for text files
            text_content = await ContentProcessor._decode_content(content_for_analysis)
            
            # Calculate score
            score = ContentProcessor.calculate_file_score(text_content)
            
            return raw_content, text_content, score
            
        except Exception as e:
            logger.warning(f"Error processing file content: {e}")
            return raw_content, "", 0.0

    @staticmethod
    async def _decode_content(content: bytes) -> str:
        """Decode content with proper encoding detection"""
        if not content:
            return ""
            
        try:
            # First try UTF-8 (most common)
            return content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                # Use chardet to detect encoding
                detected = await run_in_threadpool(chardet.detect, content)
                encoding = detected.get('encoding', 'utf-8') if detected else 'utf-8'
                confidence = detected.get('confidence', 0) if detected else 0
                
                if confidence > 0.7:  # Only use if reasonably confident
                    return content.decode(encoding, errors='replace')
                else:
                    # Fallback to latin-1 which can decode any byte sequence
                    return content.decode('latin-1', errors='replace')
                    
            except Exception as e:
                logger.warning(f"Encoding detection failed: {e}")
                # Final fallback
                return content.decode('utf-8', errors='ignore')

    @staticmethod
    def calculate_file_score(file_content: str) -> float:
        """Calculate a score based on file content with improved algorithm"""
        if not file_content or not file_content.strip():
            return 0.0
        
        try:
            # Content metrics
            word_count = len(file_content.split())
            char_count = len(file_content)
            line_count = file_content.count('\n') + 1
            
            # Quality indicators
            unique_words = len(set(file_content.lower().split()))
            avg_word_length = char_count / max(word_count, 1)
            
            # Calculate score with improved algorithm
            base_score = min(50.0, (word_count * 0.05) + (char_count * 0.005))
            complexity_bonus = min(30.0, (unique_words * 0.1) + (avg_word_length * 2))
            structure_bonus = min(20.0, line_count * 0.2)
            
            total_score = base_score + complexity_bonus + structure_bonus
            return round(min(100.0, total_score), 2)
            
        except Exception as e:
            logger.warning(f"Error calculating file score: {e}")
            return 0.0

class MetadataHandler:
    """Metadata handling utility class"""
    
    @staticmethod
    def parse_metadata(metadata_str: Optional[str]) -> Optional[Dict[str, Any]]:
        """Safely parse metadata JSON string"""
        if not metadata_str:
            return None
            
        try:
            parsed = json.loads(metadata_str)
            # Validate that it's a dictionary
            if not isinstance(parsed, dict):
                logger.warning(f"Metadata must be a JSON object, got: {type(parsed)}")
                return None
            return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid metadata JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing metadata: {e}")
            return None

async def get_client_ip(request: Request) -> str:
    """Get client IP address with proper header checking"""
    # Check for forwarded headers (common in load balancer setups)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback to direct client IP
    return request.client.host if request.client else "unknown"

async def generate_safe_filename(
    original_filename: str, 
    custom_filename: Optional[str] = None
) -> str:
    """Generate a safe, unique filename"""
    file_extension = Path(original_filename).suffix.lower()
    
    if custom_filename:
        # Sanitize custom filename
        safe_name = FileValidator.validate_filename(custom_filename)
        filename = f"{safe_name}{file_extension}"
    else:
        # Generate UUID-based filename
        filename = f"{uuid.uuid4().hex}{file_extension}"
    
    return filename

@router.post(
    "/upload",
    response_model=MultipleFileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    request: Request,
    file: UploadFile = File(..., description="Single file to upload"),
    folder: Optional[str] = Form(None, description="S3 folder path"),
    custom_filename: Optional[str] = Form(
        None, description="Custom filename (without extension)"
    ),
    user_id: Optional[str] = Form(
        None, description="User ID associated with the upload"
    ),
    metadata: Optional[str] = Form(
        None, description="Additional metadata as JSON string"
    ),
):
    """Upload a single file to AWS S3 bucket and store record in PostgreSQL"""
    try:
        # Validate file
        FileValidator.validate_file_basic(file)
        
        # Process file content
        raw_content, text_content, score = await ContentProcessor.read_file_content_safely(file)
        
        # Reset file pointer for S3 upload
        await file.seek(0)

        # Generate safe filename
        filename = await generate_safe_filename(file.filename, custom_filename)

        # Upload to S3
        result = await s3_service.upload_file(file, filename, folder)

        # Parse metadata
        upload_metadata = MetadataHandler.parse_metadata(metadata)

        # Get client IP
        client_ip = await get_client_ip(request)

        # Store in database
        db_record = await uploads_service.create_upload_record(
            original_filename=file.filename,
            s3_key=result["s3_key"],
            s3_url=result["file_url"],
            file_size=result["file_size"],
            content_type=result["content_type"],
            file_content=text_content,
            score=score,
            folder_path=folder,
            user_id=user_id,
            metadata=upload_metadata,
            upload_ip=client_ip,
        )

        logger.info(
            f"File uploaded successfully: {result['s3_key']}, "
            f"DB ID: {db_record['id'] if db_record else 'N/A'}, "
            f"Score: {score}, Size: {result['file_size']} bytes"
        )

        return MultipleFileUploadResponse(
            uploaded_files=[
                UploadedFileInfo(
                    original_filename=file.filename,
                    s3_key=result["s3_key"],
                    file_url=result["file_url"],
                    file_size=result["file_size"],
                    content_type=result["content_type"],
                )
            ],
            total_uploaded=1,
            total_failed=0,
            errors=None,
            message="File uploaded and recorded successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Upload failed: {str(e)}"
        )

@router.post(
    "/upload-multiple",
    response_model=MultipleFileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_multiple_files(
    request: Request,
    files: List[UploadFile] = File(..., description="Multiple files to upload"),
    folder: Optional[str] = Form(None, description="S3 folder path for all files"),
    prefix: Optional[str] = Form(None, description="Filename prefix for all files"),
    user_id: Optional[str] = Form(
        None, description="User ID associated with the uploads"
    ),
    metadata: Optional[str] = Form(
        None, description="Additional metadata as JSON string for all files"
    ),
):
    """Upload multiple files to AWS S3 bucket and store records in PostgreSQL"""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )
    
    if len(files) > 50:  # Reasonable limit for multiple uploads
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many files. Maximum 50 files per request"
        )

    try:
        uploaded_files = []
        errors = []

        # Parse metadata once for all files
        upload_metadata = MetadataHandler.parse_metadata(metadata)

        # Get client IP once
        client_ip = await get_client_ip(request)

        # Sanitize prefix if provided
        safe_prefix = None
        if prefix:
            safe_prefix = FileValidator.validate_filename(prefix)

        for i, file in enumerate(files):
            try:
                # Validate file
                FileValidator.validate_file_basic(file)
                
                # Process file content
                raw_content, text_content, score = await ContentProcessor.read_file_content_safely(file)
                
                # Reset file pointer for S3 upload
                await file.seek(0)

                # Generate filename with prefix
                file_extension = Path(file.filename).suffix.lower()
                filename_prefix = f"{safe_prefix}_" if safe_prefix else ""
                filename = f"{filename_prefix}{uuid.uuid4().hex}{file_extension}"

                # Upload to S3
                result = await s3_service.upload_file(file, filename, folder)

                # Store in database
                db_record = await uploads_service.create_upload_record(
                    original_filename=file.filename,
                    s3_key=result["s3_key"],
                    s3_url=result["file_url"],
                    file_size=result["file_size"],
                    content_type=result["content_type"],
                    file_content=text_content,
                    score=score,
                    folder_path=folder,
                    user_id=user_id,
                    metadata=upload_metadata,
                    upload_ip=client_ip,
                )

                uploaded_files.append(
                    UploadedFileInfo(
                        original_filename=file.filename,
                        s3_key=result["s3_key"],
                        file_url=result["file_url"],
                        file_size=result["file_size"],
                        content_type=result["content_type"],
                    )
                )

                logger.info(
                    f"File {i+1}/{len(files)} uploaded: {result['s3_key']}, "
                    f"DB ID: {db_record['id'] if db_record else 'N/A'}, Score: {score}"
                )

            except HTTPException as e:
                errors.append(
                    UploadError(
                        filename=file.filename or f"file_{i+1}",
                        error=e.detail,
                        status_code=e.status_code,
                    )
                )
                logger.warning(f"File upload failed: {file.filename} - {e.detail}")
            except Exception as e:
                errors.append(
                    UploadError(
                        filename=file.filename or f"file_{i+1}",
                        error=str(e),
                        status_code=500,
                    )
                )
                logger.error(f"File upload failed: {file.filename} - {e}", exc_info=True)

        success_count = len(uploaded_files)
        failed_count = len(errors)

        # Determine appropriate status message
        if success_count == 0:
            message = f"All {failed_count} files failed to upload"
        elif failed_count == 0:
            message = f"All {success_count} files uploaded successfully"
        else:
            message = f"Upload completed with mixed results. Success: {success_count}, Failed: {failed_count}"

        return MultipleFileUploadResponse(
            uploaded_files=uploaded_files,
            total_uploaded=success_count,
            total_failed=failed_count,
            errors=errors if errors else None,
            message=message,
        )

    except Exception as e:
        logger.error(f"Multiple upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Multiple upload failed: {str(e)}"
        )

@router.get("", response_model=FileUploadListResponse)
async def list_upload_records(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    folder: Optional[str] = Query(None, description="Filter by folder"),
    limit: int = Query(100, ge=1, le=1000, description="Number of records per page"),
    page: int = Query(1, ge=1, description="Page number"),
):
    """List file upload records from PostgreSQL database with pagination"""
    try:
        offset = (page - 1) * limit
        result = await uploads_service.list_uploads(user_id, folder, limit, offset)

        total_pages = max(1, (result["total_count"] + limit - 1) // limit)

        return FileUploadListResponse(
            data=result["records"],
            total_count=result["total_count"],
            page=page,
            limit=limit,
            total_pages=total_pages,
        )

    except Exception as e:
        logger.error(f"Failed to list upload records: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Failed to retrieve upload records: {str(e)}"
        )

@router.delete("/{s3_key:path}", response_model=DeleteFileResponse)
async def delete_upload_record(s3_key: str):
    """Delete file upload record from PostgreSQL database and S3"""
    if not s3_key or s3_key.strip() == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3 key cannot be empty"
        )

    try:
        # First check if record exists in database
        record = await uploads_service.get_upload_record(s3_key)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Record not found in database"
            )

        # Delete from S3
        s3_success = await s3_service.delete_file(s3_key)
        if not s3_success:
            logger.warning(f"File not found in S3: {s3_key}")
            # Continue with database deletion even if S3 delete fails
            # (file might have been manually deleted from S3)

        # Delete from database
        db_success = await uploads_service.delete_upload_record(s3_key)
        
        if db_success:
            logger.info(f"Successfully deleted file and record: {s3_key}")
            return DeleteFileResponse(
                message="File and record deleted successfully",
                deleted_key=s3_key,
                success=True,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete database record"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete failed for {s3_key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Delete operation failed: {str(e)}"
        )