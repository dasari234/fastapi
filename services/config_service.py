#10 sep2025
from typing import Any, Dict, Optional, Tuple

from fastapi import status
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.files import SystemConfig


class ConfigService:
    # Default configuration values
    DEFAULT_CONFIG = {
        "file_history_retention_days": "365",  # Keep file history for 1 year
        "max_file_versions": "10",  # Maximum versions to keep per file
        "file_download_logging": "true",  # Log file downloads
        "file_view_logging": "true",  # Log file views
        "admin_history_access": "true",  # Allow admins to view all file history
        "user_history_access": "true",  # Allow users to view their own history
        "history_export_limit": "1000",  # Max records for export
        "auto_cleanup_history": "true",  # Automatically cleanup old history
    }
    
    async def initialize_default_config(self, db: AsyncSession) -> bool:
        """Initialize default configuration if not exists"""
        try:
            for key, value in self.DEFAULT_CONFIG.items():
                # Check if config already exists
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.config_key == key)
                )
                existing = result.scalar_one_or_none()
                
                if not existing:
                    config = SystemConfig(
                        config_key=key,
                        config_value=value,
                        config_type=self._get_config_type(value),
                        description=self._get_config_description(key),
                        is_editable=True
                    )
                    db.add(config)
            
            await db.commit()
            return True
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error initializing default config: {e}")
            return False
    
    def _get_config_type(self, value: str) -> str:
        """Determine config type from value"""
        if value.lower() in ('true', 'false'):
            return 'boolean'
        elif value.isdigit():
            return 'number'
        elif value.startswith('{') and value.endswith('}'):
            return 'json'
        else:
            return 'string'
    
    def _get_config_description(self, key: str) -> str:
        """Get description for config key"""
        descriptions = {
            "file_history_retention_days": "Number of days to keep file history records",
            "max_file_versions": "Maximum number of versions to keep for each file",
            "file_download_logging": "Enable logging of file download events",
            "file_view_logging": "Enable logging of file view events",
            "admin_history_access": "Allow administrators to view all file history",
            "user_history_access": "Allow users to view their own file history",
            "history_export_limit": "Maximum number of records to allow for export",
            "auto_cleanup_history": "Automatically cleanup old history records",
        }
        return descriptions.get(key, "System configuration")
    
    async def get_config(self, key: str, db: AsyncSession) -> Tuple[Optional[Any], int]:
        """Get configuration value by key"""
        try:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            )
            config = result.scalar_one_or_none()
            
            if not config:
                return None, status.HTTP_404_NOT_FOUND
            
            # Convert value based on type
            value = self._convert_config_value(config.config_value, config.config_type)
            return value, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting config {key}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def get_all_config(self, db: AsyncSession) -> Tuple[Optional[Dict], int]:
        """Get all configuration values"""
        try:
            result = await db.execute(select(SystemConfig))
            configs = result.scalars().all()
            
            config_dict = {}
            for config in configs:
                config_dict[config.config_key] = {
                    "value": self._convert_config_value(config.config_value, config.config_type),
                    "type": config.config_type,
                    "description": config.description,
                    "is_editable": config.is_editable
                }
            
            return config_dict, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting all config: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def update_config(self, key: str, value: Any, db: AsyncSession) -> Tuple[bool, int]:
        """Update configuration value"""
        try:
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            )
            config = result.scalar_one_or_none()
            
            if not config:
                return False, status.HTTP_404_NOT_FOUND
            
            if not config.is_editable:
                return False, status.HTTP_403_FORBIDDEN
            
            # Convert value to string for storage
            str_value = str(value)
            config_type = self._get_config_type(str_value)
            
            await db.execute(
                update(SystemConfig)
                .where(SystemConfig.config_key == key)
                .values(config_value=str_value, config_type=config_type)
            )
            
            await db.commit()
            return True, status.HTTP_200_OK
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error updating config {key}: {e}")
            return False, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def _convert_config_value(self, value: str, config_type: str) -> Any:
        """Convert stored string value to appropriate type"""
        if config_type == 'boolean':
            return value.lower() == 'true'
        elif config_type == 'number':
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value
        elif config_type == 'json':
            try:
                import json
                return json.loads(value)
            except:
                return value
        else:
            return value
        
    # Add this method to your existing ConfigService class
    async def ensure_config_initialized(self, db: AsyncSession) -> bool:
        """Ensure system configuration is initialized"""
        try:
            result = await db.execute(select(SystemConfig))
            existing_configs = result.scalars().all()
            
            if not existing_configs:
                logger.warning("No system configuration found, initializing defaults...")
                return await self.initialize_default_config(db)
            
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring config initialization: {e}")
            return False

# Create global instance
config_service = ConfigService()