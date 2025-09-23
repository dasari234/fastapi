from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.notifications import NotificationType
from app.services.notification_service import notification_service


async def notify_user_created(user_id: int, user_data: dict):
    """Send notification about user creation"""
    try:
        # Import database session locally to avoid circular imports
        from app.database import get_db_context
        
        async with get_db_context() as db:
            await notification_service.create_notification(
                db=db,
                user_id=user_id,
                title="Welcome to the system!",
                message=f"Hello {user_data.get('first_name', 'there')}! Your account has been created successfully.",
                notification_type=NotificationType.SUCCESS,
                action_type="user_created",  # Add action_type
                metadata={"user_id": user_id, "event": "user_created"}  # Keep metadata for backward compatibility
            )
        logger.debug(f"User creation notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending user creation notification: {e}")


async def notify_file_uploaded(user_id: int, file_data: dict, db=None):
    """Send notification when a file is uploaded"""
    try:
        title = "File Uploaded Successfully"
        message = f"Your file '{file_data.get('original_filename')}' has been uploaded successfully."
        
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="success",
            action_type="file_uploaded",
            action_data=file_data,
            db=db
        )
        logger.info(f"File upload notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending file upload notification: {e}")


async def notify_file_deleted(user_id: int, file_data: dict, db=None):
    """Send notification when a file is deleted"""
    try:
        title = "File Deleted"
        message = f"Your file '{file_data.get('original_filename')}' has been deleted."
        
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="file_deleted",
            action_data=file_data,
            db=db
        )
        logger.info(f"File deletion notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending file deletion notification: {e}")

async def notify_login(user_id: int, login_data: dict, db: AsyncSession):
    """Send notification about user login"""
    try:
        ip_address = login_data.get('ip_address', 'Unknown')
        user_agent = login_data.get('user_agent', 'Unknown device')
        
        await notification_service.create_notification(
            db=db,
            user_id=user_id,
            title="New login detected",
            message=f"Your account was accessed from {ip_address} using {user_agent}.",
            notification_type=NotificationType.INFO,
            action_type="user_login",  # Add action_type
            metadata={
                "user_id": user_id,
                "event": "user_login",
                "ip_address": ip_address,
                "user_agent": user_agent
            }
        )
        logger.debug(f"Login notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending login notification: {e}")


async def notify_profile_updated(user_id: int, user_data: dict):
    """Send notification about profile update"""
    try:
        from app.database import get_db_context
        
        async with get_db_context() as db:
            await notification_service.create_notification(
                db=db,
                user_id=user_id,
                title="Profile updated",
                message="Your profile information has been updated successfully.",
                notification_type=NotificationType.INFO,
                action_type="profile_updated",  # Add action_type
                metadata={"user_id": user_id, "event": "profile_updated"}
            )
        logger.debug(f"Profile update notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending profile update notification: {e}")


async def notify_password_changed(user_id: int, user_data: dict):
    """Send notification about password change"""
    try:
        from app.database import get_db_context
        
        async with get_db_context() as db:
            await notification_service.create_notification(
                db=db,
                user_id=user_id,
                title="Password changed",
                message="Your password has been changed successfully.",
                notification_type=NotificationType.WARNING,
                action_type="password_changed",  # Add action_type
                metadata={"user_id": user_id, "event": "password_changed"}
            )
        logger.debug(f"Password change notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending password change notification: {e}")


async def notify_password_changed_admin(user_id: int, user_data: dict):
    """Send notification about admin-initiated password change"""
    try:
        from app.database import get_db_context
        
        async with get_db_context() as db:
            await notification_service.create_notification(
                db=db,
                user_id=user_id,
                title="Password reset by administrator",
                message="Your password has been reset by an administrator. Please change it after logging in.",
                notification_type=NotificationType.WARNING,
                action_type="password_changed_admin",  # Add action_type
                metadata={"user_id": user_id, "event": "password_changed_admin"}
            )
        logger.debug(f"Admin password change notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending admin password change notification: {e}")