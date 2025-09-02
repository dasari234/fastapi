import json
import logging
import uuid
from typing import List, Optional

from fastapi import (APIRouter, File, Form, HTTPException, Query, Request,
                     UploadFile, status)

from config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from s3_service import s3_service
from schemas import (DeleteFileResponse, FileUploadListResponse,
                     MultipleFileUploadResponse, UploadedFileInfo, UploadError)
from uploads_service import uploads_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Files"], prefix="/files")


def validate_file(file: UploadFile) -> None:
    """Validate file size and type"""
    # Check file size
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size too large. Maximum allowed: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Check file extension
    if file.filename:
        file_extension = file.filename.split(".")[-1].lower()
        allowed_extensions = []
        for extensions in ALLOWED_EXTENSIONS.values():
            allowed_extensions.extend(extensions)

        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File type '{file_extension}' not allowed. Allowed types: {', '.join(allowed_extensions)}",
            )


async def get_client_ip(request: Request) -> str:
    """Get client IP address"""
    return request.client.host if request.client else "unknown"


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
    """
    Upload a single file to AWS S3 bucket and store record in PostgreSQL
    """
    try:
        # Validate file
        validate_file(file)

        # Generate filename
        file_extension = file.filename.split(".")[-1]
        if custom_filename:
            filename = f"{custom_filename}.{file_extension}"
        else:
            filename = f"{uuid.uuid4().hex}.{file_extension}"

        # Upload to S3
        result = await s3_service.upload_file(file, filename, folder)

        # Parse metadata if provided
        upload_metadata = None
        if metadata:
            try:
                upload_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                logger.warning(f"Invalid metadata JSON: {metadata}")

        # Get client IP
        client_ip = await get_client_ip(request)

        # Store in database
        db_record = await uploads_service.create_upload_record(
            original_filename=file.filename,
            s3_key=result["s3_key"],
            s3_url=result["file_url"],
            file_size=result["file_size"],
            content_type=result["content_type"],
            folder_path=folder,
            user_id=user_id,
            metadata=upload_metadata,
            upload_ip=client_ip,
        )

        logger.info(
            f"File uploaded and recorded successfully: {result['s3_key']}, DB ID: {db_record['id'] if db_record else 'N/A'}"
        )

        # Return proper response structure
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
        logger.error(f"Upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
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
    """
    Upload multiple files to AWS S3 bucket and store records in PostgreSQL
    """
    try:
        uploaded_files = []
        errors = []

        # Parse metadata if provided
        upload_metadata = None
        if metadata:
            try:
                upload_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                logger.warning(f"Invalid metadata JSON: {metadata}")

        # Get client IP
        client_ip = await get_client_ip(request)

        for file in files:
            try:
                # Validate file
                validate_file(file)

                # Generate filename
                file_extension = file.filename.split(".")[-1]
                filename_prefix = f"{prefix}_" if prefix else ""
                filename = f"{filename_prefix}{uuid.uuid4().hex}.{file_extension}"

                # Upload to S3
                result = await s3_service.upload_file(file, filename, folder)

                # Store in database
                db_record = await uploads_service.create_upload_record(
                    original_filename=file.filename,
                    s3_key=result["s3_key"],
                    s3_url=result["file_url"],
                    file_size=result["file_size"],
                    content_type=result["content_type"],
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
                    f"File uploaded and recorded: {result['s3_key']}, DB ID: {db_record['id'] if db_record else 'N/A'}"
                )

            except HTTPException as e:
                errors.append(
                    UploadError(
                        filename=file.filename,
                        error=e.detail,
                        status_code=e.status_code,
                    )
                )
                logger.warning(f"File upload failed: {file.filename} - {e.detail}")
            except Exception as e:
                errors.append(
                    UploadError(
                        filename=file.filename,
                        error=str(e),
                        status_code=500,
                    )
                )
                logger.error(f"File upload failed: {file.filename} - {e}")

        return MultipleFileUploadResponse(
            uploaded_files=uploaded_files,
            total_uploaded=len(uploaded_files),
            total_failed=len(errors),
            errors=errors if errors else None,
            message=f"Upload completed. Success: {len(uploaded_files)}, Failed: {len(errors)}",
        )

    except Exception as e:
        logger.error(f"Multiple upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("", response_model=FileUploadListResponse)
async def list_upload_records(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    folder: Optional[str] = Query(None, description="Filter by folder"),
    limit: int = Query(100, ge=1, le=1000),
    page: int = Query(1, ge=1),
):
    """List file upload records from PostgreSQL database"""
    try:
        offset = (page - 1) * limit
        result = await uploads_service.list_uploads(user_id, folder, limit, offset)

        total_pages = (
            (result["total_count"] + limit - 1) // limit
            if result["total_count"] > 0
            else 1
        )

        return FileUploadListResponse(
            data=result["records"],
            total_count=result["total_count"],
            page=page,
            limit=limit,
            total_pages=total_pages,
        )

    except Exception as e:
        logger.error(f"Failed to list upload records: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.delete("/{s3_key}", response_model=DeleteFileResponse)
async def delete_upload_record(s3_key: str):
    """Delete file upload record from PostgreSQL database and S3"""
    try:
        # First delete from S3
        s3_success = await s3_service.delete_file(s3_key)

        if not s3_success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="File not found in S3"
            )

        # Then delete from database
        db_success = await uploads_service.delete_upload_record(s3_key)

        if db_success:
            return DeleteFileResponse(
                message="File and record deleted successfully",
                deleted_key=s3_key,
                success=True,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Record not found in database",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )