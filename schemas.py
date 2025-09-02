from typing import Dict, List, Literal, Optional

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
    id: Optional[int] = None
    original_filename: str
    s3_key: str
    s3_url: str
    file_size: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[Dict] = None
    user_id: Optional[str] = None
    folder_path: Optional[str] = None
    content_type: Optional[str] = None
    upload_ip: Optional[str] = None
    upload_status: Optional[str] = None

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