import logging
import time
from typing import Optional, Tuple

import chardet
from fastapi import UploadFile, status
from fastapi.concurrency import run_in_threadpool

from config import MAX_CONTENT_LENGTH_FOR_SCORING

logger = logging.getLogger(__name__)

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
            # Read raw content
            raw_content = await file.read()
            
            text_content = ""
            score = 0.0
            
            # Only attempt text processing for text-based files
            if file.content_type and file.content_type.startswith('text/'):
                # Limit content size for text processing
                content_for_analysis = raw_content[:MAX_CONTENT_LENGTH_FOR_SCORING]
                
                # Detect encoding for text files
                text_content = await ContentProcessor._decode_content(content_for_analysis)
                
                # Calculate score only for text content
                score = ContentProcessor.calculate_file_score(text_content)
            else:
                # For binary files, use basic score based on file size
                score = min(100.0, len(raw_content) / (1024 * 1024))
            
            processing_time = (time.time() - start_time) * 1000
            
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
            # First try UTF-8
            return content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                # Use chardet to detect encoding
                detected = await run_in_threadpool(chardet.detect, content)
                encoding = detected.get('encoding', 'utf-8') if detected else 'utf-8'
                confidence = detected.get('confidence', 0) if detected else 0
                
                if confidence > 0.7:
                    return content.decode(encoding, errors='replace')
                else:
                    return content.decode('latin-1', errors='replace')
                    
            except Exception as e:
                logger.warning(f"Encoding detection failed: {e}")
                return content.decode('utf-8', errors='ignore')

    @staticmethod
    def calculate_file_score(file_content: str) -> float:
        """Calculate a score based on file content"""
        if not file_content or not file_content.strip():
            return 0.0
        
        try:
            word_count = len(file_content.split())
            char_count = len(file_content)
            line_count = file_content.count('\n') + 1
            
            unique_words = len(set(file_content.lower().split()))
            avg_word_length = char_count / max(word_count, 1)
            
            base_score = min(50.0, (word_count * 0.05) + (char_count * 0.005))
            complexity_bonus = min(30.0, (unique_words * 0.1) + (avg_word_length * 2))
            structure_bonus = min(20.0, line_count * 0.2)
            
            total_score = base_score + complexity_bonus + structure_bonus
            return round(min(100.0, total_score), 2)
            
        except Exception as e:
            logger.warning(f"Error calculating file score: {e}")
            return 0.0
        
        
                