from pathlib import Path
from typing import Optional, Tuple

from fastapi import UploadFile, status

from app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE


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
    
    
    
    
