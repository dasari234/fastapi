from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Book(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="The Great Gatsby")
    genre: Literal["fiction", "non-fiction"] = Field(..., example="fiction")
    price: float = Field(
        ..., gt=0, description="Price must be greater than 0", example=12.99
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
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

# File Upload
class UploadedFileInfo(BaseModel):
    original_filename: str
    s3_key: str
    file_url: str
    file_size: int
    content_type: str

class UploadError(BaseModel):
    filename: str
    error: str
    status_code: int

class MultipleFileUploadResponse(BaseModel):
    uploaded_files: List[UploadedFileInfo]
    total_uploaded: int
    total_failed: int
    errors: Optional[List[UploadError]] = None
    message: str

class FileUploadRecord(BaseModel):
    id: int
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    content_type: str
    file_content: Optional[str] = None
    score: Optional[float] = 0.0
    folder_path: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    upload_ip: Optional[str] = None
    upload_status: str = "success"
    version: int = Field(1, ge=1, description="File version number")
    is_current_version: bool = Field(True, description="Whether this is the current version")
    previous_version_id: Optional[int] = Field(None, description="ID of previous version")
    version_comment: Optional[str] = Field(None, description="Comment for this version")
    created_at: str
    updated_at: str

class FileUploadListResponse(BaseModel):
    data: List[FileUploadRecord]
    total_count: int
    page: int
    limit: int
    total_pages: int

class DeleteFileResponse(BaseModel):
    message: str
    deleted_key: str
    success: bool
    
class FileVersionHistory(BaseModel):
    current_version: FileUploadRecord
    previous_versions: List[FileUploadRecord]
    total_versions: int

class VersionUploadRequest(BaseModel):
    version_comment: Optional[str] = Field(None, description="Comment for this new version")
    make_current: bool = Field(True, description="Make this the current version")
    
class FileHistoryRecord(BaseModel):
    id: int
    file_upload_id: int
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    content_type: str
    file_content: Optional[str] = None
    score: Optional[float] = 0.0
    folder_path: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    upload_ip: Optional[str] = None
    version: int
    version_comment: Optional[str] = None
    archived_at: str
    current_file_status: Optional[bool] = None

class FileHistoryResponse(BaseModel):
    history_records: List[FileHistoryRecord]
    total_count: int
    current_version: Optional[FileUploadRecord] = None

class RevertResponse(BaseModel):
    message: str
    reverted_version: FileUploadRecord
    previous_version: Optional[FileHistoryRecord] = None
    
class CombinedFileRecord(BaseModel):
    # Common fields
    id: Optional[int] = None
    file_upload_id: Optional[int] = None
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    content_type: str
    file_content: Optional[str] = None
    score: Optional[float] = 0.0
    folder_path: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    upload_ip: Optional[str] = None
    version: int
    version_comment: Optional[str] = None
    
    # Type-specific fields
    record_type: Literal["current", "history"]  # Indicates if it's current or historical
    is_current_version: Optional[bool] = None
    previous_version_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    archived_at: Optional[str] = None
    current_file_status: Optional[bool] = None  # For history records