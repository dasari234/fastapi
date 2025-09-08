import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chardet
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     Request, UploadFile, status)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from models.database import get_db
from models.schemas import (DeleteFileResponse, MultipleFileUploadResponse,
                            StandardResponse, UploadedFileInfo, UploadError)
from services.auth_service import TokenData, auth_service
from services.file_service import file_service
from services.s3_service import s3_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Files"], prefix="/files")

# Constants
MAX_CONTENT_LENGTH_FOR_SCORING = 1024 * 1024  # 1MB limit for text content analysis
CHUNK_SIZE = 8192  # 8KB chunks for memory-efficient reading

class FileValidator:
    """File validation utility class"""
    
    @staticmethod
    def validate_file_basic(file: UploadFile) -> Tuple[bool, Optional[str], Optional[int]]:
        """Basic file validation (size and type)"""
        if not file.filename:
            return False, "Filename is required", status.HTTP_400_BAD_REQUEST
            
        # Check file size
        if file.size and file.size > MAX_FILE_SIZE:
            return False, f"File size too large. Maximum allowed: {MAX_FILE_SIZE // (1024 * 1024)}MB", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

        # Check file extension
        file_extension = Path(file.filename).suffix.lower().lstrip('.')
        if not file_extension:
            return False, "File must have an extension", status.HTTP_400_BAD_REQUEST
            
        allowed_extensions = []
        for extensions in ALLOWED_EXTENSIONS.values():
            allowed_extensions.extend(extensions)

        if file_extension not in allowed_extensions:
            return False, f"File type '{file_extension}' not allowed. Allowed types: {', '.join(allowed_extensions)}", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

        return True, None, None

    @staticmethod
    def validate_filename(filename: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """Sanitize and validate filename"""
        if not filename:
            return None, "Filename cannot be empty", status.HTTP_400_BAD_REQUEST
        
        # Remove/replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        sanitized = ''.join(c if c not in invalid_chars else '_' for c in filename)
        
        # Ensure filename isn't too long
        if len(sanitized) > 255:
            sanitized = sanitized[:255]
            
        return sanitized, None, None

class ContentProcessor:
    """Content processing utility class with timing"""
    
    @staticmethod
    async def read_file_content_safely(file: UploadFile) -> Tuple[Optional[bytes], Optional[str], float, float, Optional[str], Optional[int]]:
        """
        Safely read file content with encoding detection, scoring, and timing
        Returns: (raw_content, text_content, score, processing_time_ms, error_message, status_code)
        """
        start_time = time.time()
        raw_content = None
        try:
            # Read raw content - this is where the processing time should be measured
            raw_content = await file.read()
            
            text_content = ""
            score = 0.0
            
            # Only attempt text processing for text-based files
            if file.content_type and file.content_type.startswith('text/'):
                # Limit content size for text processing to avoid memory issues
                content_for_analysis = raw_content[:MAX_CONTENT_LENGTH_FOR_SCORING]
                
                # Detect encoding for text files
                text_content = await ContentProcessor._decode_content(content_for_analysis)
                
                # Calculate score only for text content
                score = ContentProcessor.calculate_file_score(text_content)
            else:
                # For binary files (PDF, images, etc.), use a basic score based on file size
                # Cap the score at 100
                score = min(100.0, len(raw_content) / (1024 * 1024))  # 1 point per MB
            
            processing_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            return raw_content, text_content, score, processing_time, None, None
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.warning(f"Error processing file content: {e}")
            return raw_content, "", 0.0, processing_time, f"Error processing file content: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR


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
    def parse_metadata(metadata_str: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int]]:
        """Safely parse metadata JSON string"""
        if not metadata_str:
            return None, None, None
            
        try:
            parsed = json.loads(metadata_str)
            # Validate that it's a dictionary
            if not isinstance(parsed, dict):
                return None, "Metadata must be a JSON object", status.HTTP_400_BAD_REQUEST
            return parsed, None, None
        except json.JSONDecodeError as e:
            return None, f"Invalid metadata JSON: {str(e)}", status.HTTP_400_BAD_REQUEST
        except Exception as e:
            return None, f"Unexpected error parsing metadata: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR


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
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Generate a safe, unique filename"""
    file_extension = Path(original_filename).suffix.lower()
    
    if custom_filename:
        # Sanitize custom filename
        safe_name, error, status_code = FileValidator.validate_filename(custom_filename)
        if error:
            return None, error, status_code
        filename = f"{safe_name}{file_extension}"
    else:
        # Generate UUID-based filename
        filename = f"{uuid.uuid4().hex}{file_extension}"
    
    return filename, None, None


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
    current_user_result: Tuple[Optional[TokenData], int] = Depends(auth_service.get_current_user)
):
    """Upload a single file to AWS S3 bucket and store record in PostgreSQL"""
    try:
        # Extract TokenData from tuple
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            return MultipleFileUploadResponse(
                success=False,
                message="Authentication failed",
                error="Invalid or expired token",
                status_code=auth_status,
                uploaded_files=[],
                total_uploaded=0,
                total_failed=1,
                errors=[UploadError(filename=file.filename or "unknown", error="Authentication failed", status_code=auth_status)]
            )
        
        # Validate file
        is_valid, error_msg, error_code = FileValidator.validate_file_basic(file)
        if not is_valid:
            return MultipleFileUploadResponse(
                success=False,
                message="File validation failed",
                error=error_msg,
                status_code=error_code,
                uploaded_files=[],
                total_uploaded=0,
                total_failed=1,
                errors=[UploadError(filename=file.filename or "unknown", error=error_msg, status_code=error_code)]
            )
        
        # Process file content - now expecting 6 return values
        raw_content, text_content, score, processing_time_ms, content_error, content_status = await ContentProcessor.read_file_content_safely(file)
        
        if content_error:
            return MultipleFileUploadResponse(
                success=False,
                message="File content processing failed",
                error=content_error,
                status_code=content_status,
                uploaded_files=[],
                total_uploaded=0,
                total_failed=1,
                errors=[UploadError(filename=file.filename or "unknown", error=content_error, status_code=content_status)]
            )
        
        # Reset file pointer for S3 upload
        await file.seek(0)

        # Generate safe filename
        filename, filename_error, filename_status = await generate_safe_filename(file.filename, custom_filename)
        if filename_error:
            return MultipleFileUploadResponse(
                success=False,
                message="Filename generation failed",
                error=filename_error,
                status_code=filename_status,
                uploaded_files=[],
                total_uploaded=0,
                total_failed=1,
                errors=[UploadError(filename=file.filename or "unknown", error=filename_error, status_code=filename_status)]
            )

        # Upload to S3
        result = await s3_service.upload_file(file, filename, folder)

        # Parse metadata
        upload_metadata, metadata_error, metadata_status = MetadataHandler.parse_metadata(metadata)
        if metadata_error:
            # Clean up S3 file if metadata parsing fails
            try:
                await s3_service.delete_file(result["s3_key"])
                logger.warning(f"Deleted file from S3 due to metadata error: {result['s3_key']}")
            except Exception as s3_error:
                logger.error(f"Failed to cleanup S3 file after metadata error: {s3_error}")
            
            return MultipleFileUploadResponse(
                success=False,
                message="Metadata parsing failed",
                error=metadata_error,
                status_code=metadata_status,
                uploaded_files=[],
                total_uploaded=0,
                total_failed=1,
                errors=[UploadError(filename=file.filename or "unknown", error=metadata_error, status_code=metadata_status)]
            )

        # Get client IP
        client_ip = await get_client_ip(request)

        # Store in database with processing time
        db_record, db_status = await file_service.create_upload_record(
            original_filename=file.filename,
            s3_key=result["s3_key"],
            s3_url=result["file_url"],
            file_size=result["file_size"],
            content_type=result["content_type"],
            file_content=text_content,
            score=score,
            folder_path=folder,
            user_id=str(current_user.user_id),
            metadata=upload_metadata,
            upload_ip=client_ip,
            processing_time_ms=processing_time_ms
        )

        if db_status != status.HTTP_201_CREATED or not db_record:
            # If S3 upload was successful but DB failed, try to delete from S3 to maintain consistency
            try:
                await s3_service.delete_file(result["s3_key"])
                logger.warning(f"Deleted file from S3 due to DB failure: {result['s3_key']}")
            except Exception as s3_error:
                logger.error(f"Failed to cleanup S3 file after DB failure: {s3_error}")

            error_msg = "Failed to create database record"
            if db_record and "error" in db_record:
                error_msg = db_record.get("error", error_msg)
            
            return MultipleFileUploadResponse(
                success=False,
                message="Database record creation failed",
                error=error_msg,
                status_code=db_status,
                uploaded_files=[],
                total_uploaded=0,
                total_failed=1,
                errors=[UploadError(filename=file.filename or "unknown", error=error_msg, status_code=db_status)]
            )

        logger.info(
            f"File uploaded successfully: {result['s3_key']}, "
            f"DB ID: {db_record['id'] if db_record else 'N/A'}, "
            f"Score: {score}, Processing time: {processing_time_ms}ms, Size: {result['file_size']} bytes"
        )

        return MultipleFileUploadResponse(
            success=True,
            status_code=status.HTTP_201_CREATED,
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
    summary="Upload multiple files",
    responses={
        201: {"description": "Files uploaded successfully"},
        400: {"description": "Invalid request or no files provided"},
        413: {"description": "Files too large"},
        415: {"description": "Unsupported file types"},
        500: {"description": "Internal server error"}
    }
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
    current_user_result: Tuple[Optional[TokenData], int] = Depends(auth_service.get_current_user)
):
    """Upload multiple files to AWS S3 bucket and store records in PostgreSQL"""
    # Extract TokenData from tuple first
    current_user, auth_status = current_user_result
    if auth_status != status.HTTP_200_OK or not current_user:
        raise HTTPException(
            status_code=auth_status,
            detail="Authentication failed: Invalid or expired token"
        )
    
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )
    
    if len(files) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many files. Maximum 50 files per request"
        )

    try:
        uploaded_files = []
        errors = []

        # Parse metadata once for all files
        upload_metadata, metadata_error, metadata_status = MetadataHandler.parse_metadata(metadata)
        if metadata_error:
            raise HTTPException(
                status_code=metadata_status,
                detail=metadata_error
            )

        # Get client IP once
        client_ip = await get_client_ip(request)

        # Sanitize prefix if provided
        safe_prefix = None
        if prefix:
            safe_prefix, prefix_error, prefix_status = FileValidator.validate_filename(prefix)
            if prefix_error:
                raise HTTPException(
                    status_code=prefix_status,
                    detail=prefix_error
                )

        for i, file in enumerate(files):
            try:
                # Validate file
                is_valid, error_msg, error_code = FileValidator.validate_file_basic(file)
                if not is_valid:
                    errors.append(UploadError(
                        filename=file.filename or f"file_{i+1}",
                        error=error_msg,
                        status_code=error_code
                    ))
                    continue
                
                # Process file content - now expecting 6 values
                raw_content, text_content, score, processing_time_ms, content_error, content_status = await ContentProcessor.read_file_content_safely(file)
                
                if content_error:
                    errors.append(UploadError(
                        filename=file.filename or f"file_{i+1}",
                        error=content_error,
                        status_code=content_status
                    ))
                    continue
                
                # Reset file pointer for S3 upload
                await file.seek(0)

                # Generate safe filename
                filename, filename_error, filename_status = await generate_safe_filename(file.filename, None)
                if filename_error:
                    errors.append(UploadError(
                        filename=file.filename or f"file_{i+1}",
                        error=filename_error,
                        status_code=filename_status
                    ))
                    continue

                # Add prefix if specified
                if safe_prefix:
                    filename = f"{safe_prefix}_{filename}"

                # Upload to S3
                result = await s3_service.upload_file(file, filename, folder)

                # Store in database with processing time
                db_record, db_status = await file_service.create_upload_record(
                    original_filename=file.filename,
                    s3_key=result["s3_key"],
                    s3_url=result["file_url"],
                    file_size=result["file_size"],
                    content_type=result["content_type"],
                    file_content=text_content,
                    score=score,
                    folder_path=folder,
                    user_id=str(current_user.user_id),
                    metadata=upload_metadata,
                    upload_ip=client_ip,
                    processing_time_ms=processing_time_ms
                )

                if db_status != status.HTTP_201_CREATED or not db_record:
                    # If S3 upload was successful but DB failed, try to delete from S3 to maintain consistency
                    try:
                        await s3_service.delete_file(result["s3_key"])
                        logger.warning(f"Deleted file from S3 due to DB failure: {result['s3_key']}")
                    except Exception as s3_error:
                        logger.error(f"Failed to cleanup S3 file after DB failure: {s3_error}")

                    error_msg = "Failed to create database record"
                    if db_record and "error" in db_record:
                        error_msg = db_record.get("error", error_msg)
                    
                    errors.append(UploadError(
                        filename=file.filename or f"file_{i+1}",
                        error=error_msg,
                        status_code=db_status
                    ))
                    continue

                uploaded_files.append(
                    UploadedFileInfo(
                        original_filename=file.filename,
                        s3_key=result["s3_key"],
                        file_url=result["file_url"],
                        file_size=result["file_size"],
                        content_type=result["content_type"],
                    )
                )

                logger.info(f"File {i+1}/{len(files)} uploaded: {result['s3_key']}")

            except HTTPException as e:
                errors.append(UploadError(
                    filename=file.filename or f"file_{i+1}",
                    error=e.detail,
                    status_code=e.status_code
                ))
                logger.warning(f"File upload failed: {file.filename} - {e.detail}")
            except Exception as e:
                errors.append(UploadError(
                    filename=file.filename or f"file_{i+1}",
                    error=str(e),
                    status_code=500,
                ))
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
            success=True,
            status_code=status.HTTP_201_CREATED,
            uploaded_files=uploaded_files,
            total_uploaded=success_count,
            total_failed=failed_count,
            errors=errors if errors else None,
            message=message,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multiple upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Multiple upload failed: {str(e)}"
        )
  
        
@router.get(
    "",
    response_model=StandardResponse,
    summary="List upload records with version info and search",
    responses={
        200: {"description": "Records retrieved successfully"},
        403: {"description": "Forbidden - insufficient permissions"},
        500: {"description": "Internal server error"}
    }
)
async def list_upload_records(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    folder: Optional[str] = Query(None, description="Filter by folder"),
    search: Optional[str] = Query(None, description="Search across filename, content, user details"),
    show_all_versions: bool = Query(False, description="Show all versions or only current"),
    limit: int = Query(10, ge=1, le=1000, description="Number of records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user_result: Tuple[Optional[TokenData], int] = Depends(auth_service.get_current_user_dependency()),
    db: AsyncSession = Depends(get_db)
):
    """List file upload records with version control and search capability"""
    try:
        # Extract TokenData from tuple           
        current_user, status_code = current_user_result
        if status_code != status.HTTP_200_OK or not current_user:
            return StandardResponse(
                success=False,
                message="Authentication failed",
                error="Invalid or expired token",
                status_code=status_code
            )
            
        # Non-admin users can only see their own files
        if current_user.role != "admin": 
            user_id = str(current_user.user_id)
            
        # Handle empty search parameter
        if search == "" or search == " ":
            search = None
            
        offset = (page - 1) * limit
               
        # Get uploads based on version filter
        if show_all_versions:
            result, status_code = await file_service.list_uploads(user_id, folder, search, limit, offset, db)
        else:
            # Only show current versions
            result, status_code = await file_service.list_current_versions(user_id, folder, search, limit, offset, db)
        
        if status_code != status.HTTP_200_OK:
            return StandardResponse(
                success=False,
                message="Failed to retrieve upload records",
                error="Database query failed",
                status_code=status_code
            )
        
        total_pages = max(1, (result["total_count"] + limit - 1) // limit)

        return StandardResponse(
            success=True,
            message="Records retrieved successfully",
            data={
                "records": result["records"],
                "total_count": result["total_count"],
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "show_all_versions": show_all_versions,
                "search_query": result.get("search_query"),
                "has_search": search is not None
            },
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to list upload records: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message="Failed to retrieve upload records",
            error=f"Internal server error: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.delete(
    "/{s3_key:path}",
    response_model=DeleteFileResponse,
    summary="Delete upload record",
    responses={
        200: {"description": "Record deleted successfully"},
        400: {"description": "Invalid S3 key"},
        403: {"description": "Forbidden - insufficient permissions"},
        404: {"description": "Record not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_upload_record(
    s3_key: str,
    current_user_result: Tuple[Optional[TokenData], int] = Depends(auth_service.get_current_user)
):
    """Delete file upload record from PostgreSQL database and S3"""
    # Extract TokenData from tuple
    current_user, auth_status = current_user_result
    if auth_status != status.HTTP_200_OK or not current_user:
        return DeleteFileResponse(
            success=False,
            message="Authentication failed",
            error="Invalid or expired token",
            status_code=auth_status,
            deleted_key=None
        )
        
    if not s3_key or s3_key.strip() == "":
        return DeleteFileResponse(
            success=False,
            message="Invalid S3 key",
            error="S3 key cannot be empty",
            status_code=status.HTTP_400_BAD_REQUEST,
            deleted_key=None
        )

    try:
        # First check if record exists in database
        record, record_status = await file_service.get_upload_record(s3_key)
        if record_status == status.HTTP_404_NOT_FOUND:
            return DeleteFileResponse(
                success=False,
                message="Record not found",
                error="Record not found in database",
                status_code=status.HTTP_404_NOT_FOUND,
                deleted_key=s3_key
            )
        elif record_status != status.HTTP_200_OK:
            return DeleteFileResponse(
                success=False,
                message="Database error",
                error="Failed to retrieve record from database",
                status_code=record_status,
                deleted_key=s3_key
            )

        # Check permissions - non-admin users can only delete their own files
        if current_user.role != "admin" and record["user_id"] != str(current_user.user_id):
            return DeleteFileResponse(
                success=False,
                message="Permission denied",
                error="You can only delete your own files",
                status_code=status.HTTP_403_FORBIDDEN,
                deleted_key=s3_key
            )

        # Delete from S3 first
        s3_result, s3_status = await s3_service.delete_file(s3_key)
        if s3_status != status.HTTP_200_OK:
            # If S3 deletion fails, don't proceed with DB deletion
            error_msg = s3_result.get("error", "Unknown S3 error") if isinstance(s3_result, dict) else "S3 deletion failed"
            return DeleteFileResponse(
                success=False,
                message="S3 deletion failed",
                error=error_msg,
                status_code=s3_status,
                deleted_key=s3_key
            )

        # Delete from database
        db_result, db_status = await file_service.delete_upload_record(s3_key)
        if db_status != status.HTTP_200_OK:
            # If DB deletion fails but S3 was successful, log the inconsistency
            logger.error(f"Inconsistent state: S3 file deleted but DB record remains for key: {s3_key}")
            return DeleteFileResponse(
                success=False,
                message="Database deletion failed",
                error="File deleted from S3 but database record could not be removed",
                status_code=db_status,
                deleted_key=s3_key
            )

        logger.info(f"Successfully deleted file: {s3_key} by user: {current_user.user_id}")
        return DeleteFileResponse(
            success=True,
            message="File deleted successfully",
            deleted_key=s3_key,
            status_code=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Delete operation failed: {e}", exc_info=True)
        return DeleteFileResponse(
            success=False,
            message="Delete operation failed",
            error=f"Internal server error: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            deleted_key=s3_key
        )
        
