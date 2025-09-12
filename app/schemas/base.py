from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class StandardResponse(BaseModel):
    """Standard API response format"""
    success: bool = Field(..., description="Whether the request was successful")
    message: str = Field(..., description="Human-readable message")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message if any")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"id": 1},
                "error": None,
                "status_code": 200
            }
        }


class ErrorResponse(BaseModel):
    """Error response format"""
    error: str = Field(..., description="Error type")
    detail: Optional[str] = Field(None, description="Detailed error message")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "error": "Validation Error",
                "detail": "Invalid input data",
                "status_code": 422
            }
        }


class SuccessResponse(BaseModel):
    """Simple success response"""
    message: str = Field(..., description="Success message")
    status_code: int = Field(..., description="HTTP status code")
    data: Optional[dict] = Field(None, description="Response data")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "message": "Operation completed successfully",
                "status_code": 200,
                "data": {"id": 1}
            }
        }