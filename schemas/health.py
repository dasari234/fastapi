from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Comprehensive health check response"""
    success: bool = Field(..., description="Whether the health check was successful")
    status: str = Field(..., description="Overall status (healthy/unhealthy)")
    database: str = Field(..., description="Database type")
    connection: str = Field(..., description="Connection status")
    database_name: Optional[str] = Field(None, description="Database name")
    postgresql_version: Optional[str] = Field(None, description="PostgreSQL version")
    environment: str = Field(..., description="Environment name")
    response_time_ms: float = Field(..., description="Response time in milliseconds")
    error: Optional[str] = Field(None, description="Error message if any")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "success": True,
                "status": "healthy",
                "database": "NeonDB",
                "connection": "active",
                "database_name": "mydatabase",
                "postgresql_version": "15.0",
                "environment": "production",
                "response_time_ms": 45.2,
                "error": None,
                "status_code": 200
            }
        }

class SimpleHealthResponse(BaseModel):
    """Simple health check response"""
    success: bool = Field(..., description="Whether the health check was successful")
    status: str = Field(..., description="Overall status")
    service: str = Field(..., description="Service name")
    message: Optional[str] = Field(None, description="Additional message")
    error: Optional[str] = Field(None, description="Error message if any")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "success": True,
                "status": "healthy",
                "service": "bookstore-api",
                "message": "Service is running",
                "error": None,
                "status_code": 200
            }
        }

class DBHealthResponse(BaseModel):
    """Database health check response"""
    success: bool = Field(..., description="Whether the health check was successful")
    status: str = Field(..., description="Database status")
    message: str = Field(..., description="Status message")
    error: Optional[str] = Field(None, description="Error message if any")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "success": True,
                "status": "connected",
                "message": "Database is available",
                "error": None,
                "status_code": 200
            }
        }