import json
from typing import Any, Dict, Optional, Tuple

from fastapi import status


class MetadataHandler:
    """Metadata handling utility class"""
    
    @staticmethod
    def parse_metadata(metadata_str: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int]]:
        """Safely parse metadata JSON string"""
        if not metadata_str:
            return None, None, None
            
        try:
            parsed = json.loads(metadata_str)
            if not isinstance(parsed, dict):
                return None, "Metadata must be a JSON object", status.HTTP_400_BAD_REQUEST
            return parsed, None, None
        except json.JSONDecodeError as e:
            return None, f"Invalid metadata JSON: {str(e)}", status.HTTP_400_BAD_REQUEST
        except Exception as e:
            return None, f"Unexpected error parsing metadata: {str(e)}", status.HTTP_500_INTERNAL_SERVER_ERROR
        
        
                