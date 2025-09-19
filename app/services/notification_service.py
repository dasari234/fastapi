from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import status
from loguru import logger
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationPreference
from app.worker.tasks import send_notification


class NotificationService:
    
    async def create_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        action_type: str,
        action_data: Optional[Dict[str, Any]] = None,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Create a new notification and queue it for delivery"""
        async def _create_notification(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Create notification record
                notification = Notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    action_type=action_type,
                    action_data=action_data or {},
                )
                
                session.add(notification)
                await session.commit()
                await session.refresh(notification)
                
                # Queue notification for delivery
                send_notification.delay(notification.id)
                
                return notification.to_dict(), status.HTTP_201_CREATED
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating notification: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _create_notification(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _create_notification(session)
    
    async def get_user_notifications(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get notifications for a user"""
        async def _get_notifications(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Build query
                query = select(Notification).where(Notification.user_id == user_id)
                
                if unread_only:
                    query = query.where(Notification.is_read == False)
                
                query = query.order_by(Notification.created_at.desc())
                
                # Count total
                count_query = query.with_only_columns(func.count()).order_by(None)
                total_count_result = await session.execute(count_query)
                total_count = total_count_result.scalar() or 0
                
                # Get paginated results
                query = query.offset(offset).limit(limit)
                result = await session.execute(query)
                notifications = result.scalars().all()
                
                notifications_data = [n.to_dict() for n in notifications]
                
                return {
                    "notifications": notifications_data,
                    "total_count": total_count,
                    "unread_count": await self._get_unread_count(session, user_id),
                }, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error getting notifications: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _get_notifications(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _get_notifications(session)
    
    async def mark_as_read(
        self,
        notification_id: int,
        user_id: int,
        db: AsyncSession = None,
    ) -> Tuple[bool, int]:
        """Mark a notification as read"""
        async def _mark_as_read(session: AsyncSession) -> Tuple[bool, int]:
            try:
                result = await session.execute(
                    update(Notification)
                    .where(and_(
                        Notification.id == notification_id,
                        Notification.user_id == user_id
                    ))
                    .values(is_read=True, read_at=datetime.now(timezone.utc))
                )
                
                await session.commit()
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error marking notification as read: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _mark_as_read(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _mark_as_read(session)
    
    async def mark_all_as_read(
        self,
        user_id: int,
        db: AsyncSession = None,
    ) -> Tuple[bool, int]:
        """Mark all notifications as read for a user"""
        async def _mark_all_as_read(session: AsyncSession) -> Tuple[bool, int]:
            try:
                result = await session.execute(
                    update(Notification)
                    .where(and_(
                        Notification.user_id == user_id,
                        Notification.is_read == False
                    ))
                    .values(is_read=True, read_at=datetime.now(timezone.utc))
                )
                
                await session.commit()
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error marking all notifications as read: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _mark_all_as_read(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _mark_all_as_read(session)
    
    async def _get_unread_count(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> int:
        """Get count of unread notifications for a user"""
        try:
            result = await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(and_(
                    Notification.user_id == user_id,
                    Notification.is_read == False
                ))
            )
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting unread count: {e}")
            return 0
    
    async def get_notification_preferences(
        self,
        user_id: int,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get notification preferences for a user"""
        async def _get_preferences(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(NotificationPreference)
                    .where(NotificationPreference.user_id == user_id)
                )
                preference = result.scalar_one_or_none()
                
                if not preference:
                    # Create default preferences if they don't exist
                    preference = NotificationPreference(
                        user_id=user_id,
                        email_enabled=True,
                        push_enabled=False,
                        in_app_enabled=True,
                        digest_frequency="realtime"
                    )
                    session.add(preference)
                    await session.commit()
                    await session.refresh(preference)
                
                return {
                    "email_enabled": preference.email_enabled,
                    "push_enabled": preference.push_enabled,
                    "in_app_enabled": preference.in_app_enabled,
                    "digest_frequency": preference.digest_frequency,
                }, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error getting notification preferences: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _get_preferences(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _get_preferences(session)
    
    async def update_notification_preferences(
        self,
        user_id: int,
        preferences: Dict[str, Any],
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Update notification preferences for a user"""
        async def _update_preferences(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(NotificationPreference)
                    .where(NotificationPreference.user_id == user_id)
                )
                preference = result.scalar_one_or_none()
                
                if not preference:
                    preference = NotificationPreference(user_id=user_id)
                    session.add(preference)
                
                # Update fields
                for key, value in preferences.items():
                    if hasattr(preference, key):
                        setattr(preference, key, value)
                
                await session.commit()
                await session.refresh(preference)
                
                return {
                    "email_enabled": preference.email_enabled,
                    "push_enabled": preference.push_enabled,
                    "in_app_enabled": preference.in_app_enabled,
                    "digest_frequency": preference.digest_frequency,
                }, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error updating notification preferences: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _update_preferences(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _update_preferences(session)


# Create global instance
notification_service = NotificationService()
