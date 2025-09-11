# 10 sep2025
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import status
from loguru import logger
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.files import FileHistory
from services.config_service import config_service


class FileHistoryService:
    async def log_file_action(
        self,
        db: AsyncSession,
        file_upload_id: int,
        s3_key: str,
        action: str,
        action_by: int,
        action_details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[bool, int]:
        """Log a file action to history"""
        try:
            await config_service.ensure_config_initialized(db)
            # Check if logging is enabled for this action type
            if action in ['download', 'view']:
                config_key = f"file_{action}_logging"
                logging_enabled, status_code = await config_service.get_config(config_key, db)
                if status_code == status.HTTP_200_OK and not logging_enabled:
                    logger.info(f"Logging disabled for {action} actions")
                    return True, status.HTTP_200_OK  # Logging disabled, but not an error
                elif status_code != status.HTTP_200_OK:
                    logger.warning(f"Failed to get config for {config_key}, status: {status_code}")

            # Create history record
            history = FileHistory(
                file_upload_id=file_upload_id,
                s3_key=s3_key,
                action=action,
                action_by=action_by,
                action_details=action_details or {},
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.add(history)
            await db.commit()
            await db.refresh(history)
            
            logger.info(f"Logged file action: {action} for {s3_key} by user {action_by}, ID: {history.id}")
            return True, status.HTTP_201_CREATED
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error logging file action: {e}", exc_info=True)
            return False, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    
    async def get_file_history(
        self,
        db: AsyncSession,
        s3_key: str,
        user_id: Optional[int] = None,
        is_admin: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[Optional[List[Dict]], int]:
        """Get file history with access control"""
        try:
            # Check access permissions
            if not is_admin:
                config_enabled, status_code = await config_service.get_config("user_history_access", db)
                if not config_enabled:
                    return None, status.HTTP_403_FORBIDDEN
            
            query = select(FileHistory).where(FileHistory.s3_key == s3_key)
            
            # Non-admins can only see their own actions unless configured otherwise
            if not is_admin and user_id:
                config_enabled, status_code = await config_service.get_config("admin_history_access", db)
                if not config_enabled:
                    query = query.where(FileHistory.action_by == user_id)
            
            result = await db.execute(
                query.order_by(desc(FileHistory.created_at))
                .limit(limit)
                .offset(offset)
            )
            
            history_records = result.scalars().all()
            
            history_list = []
            for record in history_records:
                history_list.append({
                    "id": record.id,
                    "action": record.action,
                    "action_by": record.action_by,
                    "action_details": record.action_details,
                    "ip_address": record.ip_address,
                    "user_agent": record.user_agent,
                    "created_at": record.created_at.isoformat() if record.created_at else None
                })
            
            return history_list, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting file history for {s3_key}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def get_user_file_history(
        self,
        db: AsyncSession,
        user_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[Optional[List[Dict]], int]:
        """Get all file actions by a specific user"""
        try:
            result = await db.execute(
                select(FileHistory)
                .where(FileHistory.action_by == user_id)
                .order_by(desc(FileHistory.created_at))
                .limit(limit)
                .offset(offset)
            )
            
            history_records = result.scalars().all()
            
            history_list = []
            for record in history_records:
                history_list.append({
                    "id": record.id,
                    "s3_key": record.s3_key,
                    "action": record.action,
                    "action_details": record.action_details,
                    "ip_address": record.ip_address,
                    "created_at": record.created_at.isoformat() if record.created_at else None
                })
            
            return history_list, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting user file history for {user_id}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def cleanup_old_history(self, db: AsyncSession) -> Tuple[int, int]:
        """Cleanup old history records based on retention policy"""
        try:
            retention_days, status_code = await config_service.get_config("file_history_retention_days", db)
            if status_code != status.HTTP_200_OK:
                retention_days = 365  # Default to 1 year
            
            auto_cleanup, status_code = await config_service.get_config("auto_cleanup_history", db)
            if not auto_cleanup:
                return 0, status.HTTP_200_OK  # Cleanup disabled
            
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            
            result = await db.execute(
                delete(FileHistory)
                .where(FileHistory.created_at < cutoff_date)
            )
            
            await db.commit()
            deleted_count = result.rowcount
            
            logger.info(f"Cleaned up {deleted_count} old history records")
            return deleted_count, status.HTTP_200_OK
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error cleaning up old history: {e}")
            return 0, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def get_history_stats(
        self,
        db: AsyncSession,
        days: int = 30
    ) -> Tuple[Optional[Dict], int]:
        """Get file history statistics"""
        try:
            # Total actions
            total_result = await db.execute(select(func.count(FileHistory.id)))
            total_actions = total_result.scalar() or 0
            
            # Actions by type
            actions_result = await db.execute(
                select(FileHistory.action, func.count(FileHistory.id))
                .group_by(FileHistory.action)
            )
            actions_by_type = {row[0]: row[1] for row in actions_result.all()}
            
            # Recent activity (last X days)
            recent_date = datetime.now(timezone.utc) - timedelta(days=days)
            recent_result = await db.execute(
                select(func.count(FileHistory.id))
                .where(FileHistory.created_at >= recent_date)
            )
            recent_actions = recent_result.scalar() or 0
            
            # Top users
            users_result = await db.execute(
                select(FileHistory.action_by, func.count(FileHistory.id))
                .group_by(FileHistory.action_by)
                .order_by(func.count(FileHistory.id).desc())
                .limit(10)
            )
            top_users = [{"user_id": row[0], "action_count": row[1]} for row in users_result.all()]
            
            stats = {
                "total_actions": total_actions,
                "actions_by_type": actions_by_type,
                "recent_actions": recent_actions,
                "top_users": top_users,
                "stats_period_days": days
            }
            
            return stats, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting history stats: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

# Create global instance
file_history_service = FileHistoryService()
