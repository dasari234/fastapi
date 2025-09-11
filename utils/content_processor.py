import time
from typing import Optional, Tuple

import chardet
from fastapi import UploadFile, status
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from config import MAX_CONTENT_LENGTH_FOR_SCORING


class ContentProcessor:
    """
    Utility class for reading and analyzing uploaded file content.
    Provides safe reading, encoding detection, scoring, and performance tracking.
    """

    @staticmethod
    async def read_file_content_safely(
        file: UploadFile,
    ) -> Tuple[Optional[bytes], str, float, float, Optional[str], Optional[int]]:
        """
        Safely read file content with encoding detection, scoring, and timing.

        Returns:
            raw_content (Optional[bytes]): Original file bytes
            text_content (str): Decoded text (if applicable)
            score (float): Quality/complexity score (0–100)
            processing_time_ms (float): Processing duration in milliseconds
            error_message (Optional[str]): Error message if failure
            status_code (Optional[int]): HTTP status code if failure
        """
        start_time = time.time()
        raw_content: Optional[bytes] = None

        try:
            # Read raw content
            raw_content = await file.read()
            text_content = ""
            score = 0.0

            # Handle text-based files
            if file.content_type and file.content_type.startswith("text/"):
                content_for_analysis = raw_content[:MAX_CONTENT_LENGTH_FOR_SCORING]

                text_content = await ContentProcessor._decode_content(content_for_analysis)
                score = ContentProcessor.calculate_file_score(text_content)

            else:
                # For binary files, score = size-based heuristic
                score = min(100.0, len(raw_content) / (1024 * 1024))  # MB scaling

            processing_time = (time.time() - start_time) * 1000
            return raw_content, text_content, score, processing_time, None, None

        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.warning(f"Error processing file content: {e}")
            return (
                raw_content,
                "",
                0.0,
                processing_time,
                f"Error processing file content: {e}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # Helpers
    @staticmethod
    async def _decode_content(content: bytes) -> str:
        """Decode bytes into string using best-effort encoding detection."""
        if not content:
            return ""

        # Try UTF-8 first (most common)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            pass

        try:
            # Run chardet in threadpool (non-blocking for event loop)
            detected = await run_in_threadpool(chardet.detect, content)
            encoding = detected.get("encoding", "utf-8") if detected else "utf-8"
            confidence = detected.get("confidence", 0) if detected else 0

            if confidence > 0.7:
                return content.decode(encoding, errors="replace")

            # Fallback for low-confidence detection
            return content.decode("latin-1", errors="replace")

        except Exception as e:
            logger.warning(f"Encoding detection failed: {e}")
            return content.decode("utf-8", errors="ignore")

    @staticmethod
    def calculate_file_score(file_content: str) -> float:
        """
        Calculate a "complexity score" for text files based on word count,
        character count, unique words, average word length, and structure.
        """
        if not file_content.strip():
            return 0.0

        try:
            word_count = len(file_content.split())
            char_count = len(file_content)
            line_count = file_content.count("\n") + 1

            unique_words = len(set(file_content.lower().split()))
            avg_word_length = char_count / max(word_count, 1)

            # Weighted scoring system
            base_score = min(50.0, (word_count * 0.05) + (char_count * 0.005))
            complexity_bonus = min(30.0, (unique_words * 0.1) + (avg_word_length * 2))
            structure_bonus = min(20.0, line_count * 0.2)

            return round(min(100.0, base_score + complexity_bonus + structure_bonus), 2)

        except Exception as e:
            logger.warning(f"Error calculating file score: {e}")
            return 0.0
