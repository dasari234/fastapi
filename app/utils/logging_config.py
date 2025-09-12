"""
Logging configuration for the Bookstore API using Loguru.
"""

from pathlib import Path

from loguru import logger

from app.config import DEBUG


def setup_logging():
    """Configure Loguru logging for the application."""
    
    # Ensure logs directory exists
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Remove default handler
    logger.remove()
    
    # Console logging
    logger.add(
        sink=lambda msg: print(msg, end=""),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG" if DEBUG else "INFO",
        colorize=True,
        backtrace=True,
        diagnose=DEBUG,
    )
    
    # File logging - application logs
    logger.add(
        sink="logs/app.log",
        rotation="500 MB",
        retention="10 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        backtrace=True,
        diagnose=DEBUG,
        enqueue=True,
        compression="zip"
    )
    
    # File logging - error logs only
    logger.add(
        sink="logs/error.log",
        rotation="100 MB",
        retention="30 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="ERROR",
        backtrace=True,
        diagnose=True,
        enqueue=True,
        compression="zip"
    )
    
    # File logging - access logs (HTTP requests)
    logger.add(
        sink="logs/access.log",
        rotation="200 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        filter=lambda record: "HTTP" in record["message"] or "X-Process-Time" in record.get("extra", {}),
        enqueue=True,
        compression="zip"
    )
    
    logger.info("Logging configuration completed")
    return logger


# Create a separate access logger
access_logger = logger.bind(access_log=True)


def get_logger():
    """Get the configured logger instance."""
    return logger


def get_access_logger():
    """Get the access logger instance."""
    return access_logger