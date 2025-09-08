from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .base import Base, StandardResponse
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship


class FileUploadRecord(Base):
    __tablename__ = "file_uploads"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    s3_key = Column(String(512), unique=True, index=True, nullable=False)
    s3_url = Column(Text, nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False)
    file_content = Column(Text, nullable=True)
    score = Column(Float, default=0.0)
    folder_path = Column(String(255), nullable=True)
    user_id = Column(String(50), nullable=True)
    file_metadata = Column(JSON, nullable=True)
    upload_ip = Column(String(45), nullable=True)
    upload_status = Column(String(20), default="success", nullable=False)

    processing_time_ms = Column(Float, default=0.0)
    version = Column(Integer, default=1)
    is_current_version = Column(Boolean, default=True)
    parent_version_id = Column(
        Integer, ForeignKey("file_uploads.id", ondelete="SET NULL"), nullable=True
    )

    previous_versions = relationship(
        "FileUploadRecord",
        foreign_keys=[parent_version_id],
        remote_side=[id],
        backref="next_versions",
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Index for better performance
    __table_args__ = (
        Index("ix_file_upload_user_id", "user_id"),
        Index("ix_file_upload_s3_key", "s3_key"),
        Index("ix_file_upload_version", "version"),
        Index("ix_file_upload_current_version", "is_current_version"),
        Index("ix_file_upload_s3_key_version", "s3_key", "version", unique=True),
    )


class UploadedFileInfo(BaseModel):
    """Basic file upload information"""

    original_filename: str = Field(..., description="Original filename")
    s3_key: str = Field(..., description="S3 object key")
    file_url: str = Field(..., description="Presigned URL for file access")
    file_size: int = Field(..., description="File size in bytes")
    content_type: str = Field(..., description="File content type")

    class Config:
        json_schema_extra = {
            "example": {
                "original_filename": "document.pdf",
                "s3_key": "uploads/document_abc123.pdf",
                "file_url": "https://bucket.s3.amazonaws.com/uploads/document_abc123.pdf",
                "file_size": 1024000,
                "content_type": "application/pdf",
            }
        }


class UploadError(BaseModel):
    """File upload error information"""

    filename: str = Field(..., description="Filename that failed to upload")
    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        json_schema_extra = {
            "example": {
                "filename": "document.pdf",
                "error": "File too large",
                "status_code": 413,
            }
        }


class MultipleFileUploadResponse(StandardResponse):
    """Response for multiple file uploads"""

    uploaded_files: Optional[List[UploadedFileInfo]] = Field(
        None, description="Successfully uploaded files"
    )
    total_uploaded: int = Field(0, description="Number of successfully uploaded files")
    total_failed: int = Field(0, description="Number of failed uploads")
    errors: Optional[List[UploadError]] = Field(None, description="Upload errors")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Files uploaded successfully",
                "data": None,
                "error": None,
                "status_code": 201,
                "uploaded_files": [
                    {
                        "original_filename": "document.pdf",
                        "s3_key": "uploads/document_abc123.pdf",
                        "file_url": "https://bucket.s3.amazonaws.com/uploads/document_abc123.pdf",
                        "file_size": 1024000,
                        "content_type": "application/pdf",
                    }
                ],
                "total_uploaded": 1,
                "total_failed": 0,
                "errors": None,
            }
        }


class FileUploadRecordResponse(BaseModel):
    """Complete file upload record"""

    id: int = Field(..., description="Record ID")
    original_filename: str = Field(..., description="Original filename")
    s3_key: str = Field(..., description="S3 object key")
    s3_url: str = Field(..., description="Presigned URL")
    file_size: int = Field(..., description="File size in bytes")
    content_type: str = Field(..., description="File content type")
    file_content: Optional[str] = Field(None, description="Extracted file content")
    score: float = Field(0.0, description="Content quality score")
    folder_path: Optional[str] = Field(None, description="S3 folder path")
    user_id: Optional[str] = Field(None, description="User ID who uploaded the file")
    metadata: Optional[Dict[str, Any]] = Field(None, description="File metadata")
    upload_ip: Optional[str] = Field(None, description="Uploader IP address")
    upload_status: str = Field("success", description="Upload status")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "original_filename": "document.pdf",
                "s3_key": "uploads/document_abc123.pdf",
                "s3_url": "https://bucket.s3.amazonaws.com/uploads/document_abc123.pdf",
                "file_size": 1024000,
                "content_type": "application/pdf",
                "file_content": "Extracted text content...",
                "score": 85.5,
                "folder_path": "uploads",
                "user_id": "1",
                "metadata": {"author": "John Doe"},
                "upload_ip": "192.168.1.1",
                "upload_status": "success",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z",
            }
        }


class FileUploadListResponse(BaseModel):
    """Paginated list of file uploads"""

    data: Optional[List[Dict[str, Any]]] = Field(None, description="File records")
    total_count: int = Field(0, description="Total number of records")
    page: int = Field(1, description="Current page number")
    limit: int = Field(100, description="Records per page")
    total_pages: int = Field(1, description="Total number of pages")

    class Config:
        json_schema_extra = {
            "example": {
                "data": [
                    {
                        "id": 1,
                        "original_filename": "document.pdf",
                        "s3_key": "uploads/document_abc123.pdf",
                        "s3_url": "https://bucket.s3.amazonaws.com/uploads/document_abc123.pdf",
                        "file_size": 1024000,
                        "content_type": "application/pdf",
                    }
                ],
                "total_count": 1,
                "page": 1,
                "limit": 100,
                "total_pages": 1,
            }
        }


class DeleteFileResponse(BaseModel):
    """File deletion response"""

    deleted_key: Optional[str] = Field(None, description="Deleted S3 key")

    class Config:
        json_schema_extra = {"example": {"deleted_key": "uploads/document_abc123.pdf"}}


class FileVersionInfo(BaseModel):
    """File version information"""

    id: int = Field(..., description="Version ID")
    original_filename: str = Field(..., description="Original filename")
    s3_key: str = Field(..., description="S3 object key")
    s3_url: str = Field(..., description="Presigned URL")
    file_size: int = Field(..., description="File size in bytes")
    content_type: str = Field(..., description="File content type")
    score: float = Field(..., description="Content quality score")
    processing_time_ms: float = Field(
        ..., description="Processing time in milliseconds"
    )
    version: int = Field(..., description="Version number")
    is_current_version: bool = Field(
        ..., description="Whether this is the current version"
    )
    parent_version_id: Optional[int] = Field(None, description="Parent version ID")
    user_id: str = Field(..., description="User ID who uploaded this version")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    upload_status: str = Field(..., description="Upload status")

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "original_filename": "document.pdf",
                "s3_key": "uploads/document_abc123.pdf",
                "s3_url": "https://bucket.s3.amazonaws.com/uploads/document_abc123.pdf",
                "file_size": 1024000,
                "content_type": "application/pdf",
                "score": 85.5,
                "processing_time_ms": 150.0,
                "version": 1,
                "is_current_version": True,
                "parent_version_id": None,
                "user_id": "1",
                "created_at": "2023-01-01T00:00:00Z",
                "upload_status": "success",
            }
        }


class FileVersionHistoryResponse(StandardResponse):
    """File version history response"""

    data: Optional[Dict[str, Any]] = Field(None, description="Version history data")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Version history retrieved",
                "data": {
                    "versions": [
                        {
                            "id": 1,
                            "original_filename": "document.pdf",
                            "s3_key": "uploads/document_abc123.pdf",
                            "version": 1,
                            "created_at": "2023-01-01T00:00:00Z",
                        }
                    ]
                },
                "error": None,
                "status_code": 200,
            }
        }


class FileRestoreResponse(StandardResponse):
    """File restore response"""

    data: Optional[Dict[str, Any]] = Field(None, description="Restored file data")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "File version restored",
                "data": {
                    "id": 2,
                    "original_filename": "document.pdf",
                    "s3_key": "uploads/document_abc123.pdf",
                    "version": 2,
                },
                "error": None,
                "status_code": 200,
            }
        }
