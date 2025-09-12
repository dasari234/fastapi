import uuid
from pathlib import Path
from typing import Optional, Tuple

from fastapi import Request

from app.utils.file_validator import FileValidator


async def get_client_ip(request: Request) -> str:
    """Get client IP address with proper header checking"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    return request.client.host if request.client else "unknown"

async def generate_safe_filename(
    original_filename: str, 
    custom_filename: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Generate a safe, unique filename"""
    file_extension = Path(original_filename).suffix.lower()
    
    if custom_filename:
        safe_name, error, status_code = FileValidator.validate_filename(custom_filename)
        if error:
            return None, error, status_code
        filename = f"{safe_name}{file_extension}"
    else:
        filename = f"{uuid.uuid4().hex}{file_extension}"
    
    return filename, None, None



