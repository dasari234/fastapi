from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import status
from loguru import logger
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationPreference
from app.services.websocket_manager import websocket_manager


class NotificationService:
    
    async def create_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        action_type: str = None,
        action_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Create a new notification and send via WebSocket"""
        async def _create_notification(session: AsyncSession) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                logger.debug(f"Creating notification for user {user_id}: {title}")
                
                # Use metadata if provided, otherwise use action_data
                final_action_data = metadata or action_data or {}
                
                # Determine action_type from metadata if not provided
                final_action_type = action_type
                if not final_action_type and metadata and 'event' in metadata:
                    final_action_type = metadata['event']
                elif not final_action_type:
                    final_action_type = "system_notification"
                
                # Create notification record
                notification = Notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    action_type=final_action_type,
                    action_data=final_action_data,
                )
                
                session.add(notification)
                await session.commit()
                await session.refresh(notification)
                
                # Convert to dict for WebSocket
                notification_dict = self._notification_to_dict(notification)
                
                logger.debug(f"Notification created with ID: {notification.id}")
                
                # Send real-time notification via WebSocket
                websocket_result = await self.send_realtime_notification(user_id, notification_dict)
                logger.debug(f"WebSocket notification sent: {websocket_result}")
                
                return notification_dict, status.HTTP_201_CREATED
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating notification: {e}", exc_info=True)
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _create_notification(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _create_notification(session)
            
    def _notification_to_dict(self, notification: Notification) -> Dict[str, Any]:
        """Convert notification model to dictionary"""
        return {
            "id": notification.id,
            "user_id": notification.user_id,
            "title": notification.title,
            "message": notification.message,
            "type": notification.notification_type,
            "action_type": notification.action_type,
            "action_data": notification.action_data or {},
            "is_read": notification.is_read,
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
            "is_realtime": True
        }
    
    async def get_user_notifications(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
        db: AsyncSession = None,
        current_user_role: str = None  # Add current user role to check if admin
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get notifications for a user, with user details for admin users"""
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
                
                # If current user is admin, fetch user details for each notification
                user_details_map = {}
                if current_user_role == "admin":
                    # Get all unique user IDs from notifications
                    user_ids = list(set(notification.user_id for notification in notifications))
                    
                    if user_ids:
                        from app.models.user import User
                        users_query = select(User).where(User.id.in_(user_ids))
                        users_result = await session.execute(users_query)
                        users = users_result.scalars().all()
                        
                        # Create mapping of user_id to user details
                        user_details_map = {
                            user.id: {
                                "id": user.id,
                                "email": user.email,
                                "first_name": user.first_name,
                                "last_name": user.last_name,
                                "role": user.role,
                                "is_active": user.is_active
                            }
                            for user in users
                        }
                
                notifications_data = []
                for notification in notifications:
                    notification_dict = self._notification_to_dict(notification)
                    
                    # Add user details if current user is admin
                    if current_user_role == "admin" and notification.user_id in user_details_map:
                        notification_dict["user_details"] = user_details_map[notification.user_id]
                    
                    notifications_data.append(notification_dict)
                
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
                
                # Send real-time update to user
                update_data = {
                    "type": "notification_updated",
                    "notification_id": notification_id,
                    "is_read": True,
                    "read_at": datetime.now(timezone.utc).isoformat()
                }
                await self.send_realtime_notification(user_id, update_data)
                
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
                
                # Send real-time update to user
                update_data = {
                    "type": "all_notifications_read",
                    "user_id": user_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                await self.send_realtime_notification(user_id, update_data)
                
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

    async def send_realtime_notification(
        self,
        user_id: int,
        notification_data: dict
    ):
        """Send real-time notification via WebSocket"""
        try:
            logger.debug(f"Attempting to send real-time notification to user {user_id}")
            
            # Send to specific user
            result = await websocket_manager.send_personal_message({
                "type": "notification",
                "data": notification_data
            }, user_id)
            
            logger.debug(f"Real-time notification sent to user {user_id}: {result}")
            return True
        except Exception as e:
            logger.error(f"Error sending real-time notification to user {user_id}: {e}", exc_info=True)
            return False
    
    async def send_admin_notification(
        self,
        notification_data: dict
    ):
        """Send notification to all admin users"""
        try:
            await websocket_manager.broadcast_to_admins({
                "type": "admin_notification", 
                "data": notification_data
            })
            
            logger.debug("Admin notification broadcasted")
            return True
        except Exception as e:
            logger.error(f"Error sending admin notification: {e}")
            return False

    async def mark_notification_as_read_admin(
        self,
        notification_id: int,
        admin_user_id: int,
        db: AsyncSession = None,
    ) -> Tuple[bool, int]:
        """Admin: Mark any notification as read"""
        async def _mark_as_read_admin(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # First get the notification to verify it exists and get the target user_id
                result = await session.execute(
                    select(Notification).where(Notification.id == notification_id)
                )
                notification = result.scalar_one_or_none()
                
                if not notification:
                    return False, status.HTTP_404_NOT_FOUND
                
                # Update the notification
                await session.execute(
                    update(Notification)
                    .where(Notification.id == notification_id)
                    .values(is_read=True, read_at=datetime.now(timezone.utc))
                )
                
                await session.commit()
                
                # Send real-time update to both the target user and admin
                update_data = {
                    "type": "notification_updated",
                    "notification_id": notification_id,
                    "is_read": True,
                    "read_at": datetime.now(timezone.utc).isoformat(),
                    "marked_by_admin": True,
                    "admin_user_id": admin_user_id
                }
                
                # Notify the notification owner
                await self.send_realtime_notification(notification.user_id, update_data)
                # Also notify admin who performed the action
                await self.send_realtime_notification(admin_user_id, update_data)
                
                logger.info(f"Admin {admin_user_id} marked notification {notification_id} as read for user {notification.user_id}")
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error marking notification as read (admin): {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _mark_as_read_admin(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _mark_as_read_admin(session)

    async def mark_all_as_read_admin(
        self,
        target_user_id: int = None,
        admin_user_id: int = None,
        db: AsyncSession = None,
    ) -> Tuple[bool, int]:
        """Admin: Mark all notifications as read for a specific user or all users"""
        async def _mark_all_as_read_admin(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # Build query based on target
                if target_user_id:
                    # Mark all as read for specific user
                    query = update(Notification).where(
                        and_(
                            Notification.user_id == target_user_id,
                            Notification.is_read == False
                        )
                    )
                    affected_user_id = target_user_id
                else:
                    # Mark all as read for all users (global)
                    query = update(Notification).where(
                        Notification.is_read == False
                    )
                    affected_user_id = "all_users"
                
                result = await session.execute(
                    query.values(
                        is_read=True, 
                        read_at=datetime.now(timezone.utc)
                    )
                )
                
                await session.commit()
                
                # Send real-time updates
                update_data = {
                    "type": "all_notifications_read",
                    "marked_by_admin": True,
                    "admin_user_id": admin_user_id,
                    "target_user_id": target_user_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                if target_user_id:
                    # Notify specific user
                    await self.send_realtime_notification(target_user_id, update_data)
                else:
                    # Notify all connected users
                    for user_id in list(self.active_connections.keys()):
                        await self.send_realtime_notification(user_id, update_data)
                
                # Always notify the admin who performed the action
                if admin_user_id:
                    await self.send_realtime_notification(admin_user_id, update_data)
                
                logger.info(f"Admin {admin_user_id} marked all notifications as read for {affected_user_id}")
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error marking all notifications as read (admin): {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _mark_all_as_read_admin(db)
        else:
            from app.database import get_db_context
            async with get_db_context() as session:
                return await _mark_all_as_read_admin(session)

# Create global instance
notification_service = NotificationService()