#10 sep2025
#TODO: REMOVE UNUSED IMPORTS
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.files import SystemConfig
from services.config_service import ConfigService


class ConfigInitializer:
    def __init__(self):
        self.config_service = ConfigService()
    
    async def initialize_system_config(self, db: AsyncSession) -> bool:
        """Initialize system configuration with default values"""
        try:
            logger.info("Starting system configuration initialization...")
            
            # Check if config already exists
            result = await db.execute(select(SystemConfig))
            existing_configs = result.scalars().all()
            
            if existing_configs:
                logger.info(f"Found {len(existing_configs)} existing configuration entries")
                return True  # Config already initialized
            
            # Create default configuration entries
            default_configs = [
                {
                    "config_key": "file_history_retention_days",
                    "config_value": "365",
                    "config_type": "number",
                    "description": "Number of days to keep file history records",
                    "is_editable": True
                },
                {
                    "config_key": "max_file_versions",
                    "config_value": "10",
                    "config_type": "number",
                    "description": "Maximum number of versions to keep for each file",
                    "is_editable": True
                },
                {
                    "config_key": "file_download_logging",
                    "config_value": "true",
                    "config_type": "boolean",
                    "description": "Enable logging of file download events",
                    "is_editable": True
                },
                {
                    "config_key": "file_view_logging",
                    "config_value": "true",
                    "config_type": "boolean",
                    "description": "Enable logging of file view events",
                    "is_editable": True
                },
                {
                    "config_key": "admin_history_access",
                    "config_value": "true",
                    "config_type": "boolean",
                    "description": "Allow administrators to view all file history",
                    "is_editable": True
                },
                {
                    "config_key": "user_history_access",
                    "config_value": "true",
                    "config_type": "boolean",
                    "description": "Allow users to view their own file history",
                    "is_editable": True
                },
                {
                    "config_key": "history_export_limit",
                    "config_value": "1000",
                    "config_type": "number",
                    "description": "Maximum number of records to allow for export",
                    "is_editable": True
                },
                {
                    "config_key": "auto_cleanup_history",
                    "config_value": "true",
                    "config_type": "boolean",
                    "description": "Automatically cleanup old history records",
                    "is_editable": True
                },
                {
                    "config_key": "max_file_size_mb",
                    "config_value": "100",
                    "config_type": "number",
                    "description": "Maximum file size allowed for upload in MB",
                    "is_editable": True
                },
                {
                    "config_key": "allowed_file_types",
                    "config_value": "pdf,doc,docx,xls,xlsx,ppt,pptx,txt,jpg,jpeg,png,gif",
                    "config_type": "string",
                    "description": "Comma-separated list of allowed file extensions",
                    "is_editable": True
                },
                {
                    "config_key": "session_timeout_minutes",
                    "config_value": "60",
                    "config_type": "number",
                    "description": "User session timeout in minutes",
                    "is_editable": True
                },
                {
                    "config_key": "max_login_attempts",
                    "config_value": "5",
                    "config_type": "number",
                    "description": "Maximum failed login attempts before lockout",
                    "is_editable": True
                }
            ]
            
            # Insert default configurations
            for config_data in default_configs:
                config = SystemConfig(**config_data)
                db.add(config)
                logger.info(f"Adding config: {config_data['config_key']} = {config_data['config_value']}")
            
            await db.commit()
            logger.info("System configuration initialized successfully with default values")
            return True
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to initialize system configuration: {e}", exc_info=True)
            return False
    
    async def reset_to_defaults(self, db: AsyncSession) -> bool:
        """Reset all configurations to default values"""
        try:
            logger.info("Resetting system configuration to defaults...")
            
            # Delete all existing configurations
            await db.execute("DELETE FROM system_config")
            
            # Re-initialize with defaults
            success = await self.initialize_system_config(db)
            
            if success:
                logger.info("System configuration reset to defaults successfully")
            else:
                logger.error("Failed to reset system configuration")
            
            return success
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to reset system configuration: {e}", exc_info=True)
            return False

# Create global instance
config_initializer = ConfigInitializer()