import asyncio
from datetime import datetime

from celery import Celery
from loguru import logger

from app.config import REDIS_HOST

# Initialize Celery
celery_app = Celery('notification_tasks', broker=REDIS_HOST, backend=REDIS_HOST)

@celery_app.task(name="send_user_created_notification")
def send_user_created_notification(user_id: int, user_data: dict):
    """Celery task to send user creation notification"""
    try:
        from app.database import get_db_context
        from app.services.notification_service import notification_service
        
        async def _send_notification():
            async with get_db_context() as db:
                await notification_service.create_notification(
                    db=db,
                    user_id=user_id,
                    title="Welcome to the system!",
                    message=f"Hello {user_data.get('first_name', 'there')}! Your account has been created successfully.",
                    notification_type="success",
                    action_type="user_created",
                    metadata={"user_id": user_id, "event": "user_created"}
                )
                
                # Send real-time WebSocket notification
                from app.hooks.notification_hooks import send_websocket_notification
                await send_websocket_notification(
                    user_id=user_id,
                    title="Welcome to the system!",
                    message=f"Hello {user_data.get('first_name', 'there')}! Your account has been created successfully.",
                    notification_type="success",
                    action_type="user_created"
                )
        
        # Run async function in sync context
        import asyncio
        asyncio.run(_send_notification())
        
        logger.info(f"User creation notification sent for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in user creation notification task: {e}")

@celery_app.task(name="send_user_updated_notification")
def send_user_updated_notification(user_id: int, updated_fields: dict, updated_by: int):
    """Celery task to send user update notification"""
    try:
        from app.database import get_db_context
        from app.services.notification_service import notification_service
        
        async def _send_notification():
            async with get_db_context() as db:
                title = "Profile Updated"
                message = "Your profile information has been updated successfully."
                
                # Check if it's an admin update
                if updated_by != user_id:
                    title = "Profile Updated by Administrator"
                    message = "Your profile has been updated by an administrator."
                
                await notification_service.create_notification(
                    db=db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type="info",
                    action_type="user_updated",
                    action_data={
                        "updated_fields": updated_fields,
                        "updated_by": updated_by,
                        "updated_at": datetime.now().isoformat()
                    }
                )
                
                # Send real-time WebSocket notification
                from app.hooks.notification_hooks import send_websocket_notification
                await send_websocket_notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type="info",
                    action_type="user_updated",
                    action_data={
                        "updated_fields": updated_fields,
                        "updated_by": updated_by
                    }
                )
        
        asyncio.run(_send_notification())
        logger.info(f"User update notification sent for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in user update notification task: {e}")

@celery_app.task(name="send_user_deleted_notification")
def send_user_deleted_notification(user_id: int, user_email: str, deleted_by: int, deleted_by_admin: bool = False):
    """Celery task to send user deletion notification (to admins)"""
    try:
        from app.database import get_db_context
        from app.hooks.notification_hooks import send_admin_websocket_notification
        
        async def _send_notification():
            async with get_db_context() as db:
                title = "User Account Deleted"
                message = f"User account {user_email} (ID: {user_id}) has been deleted."
                
                if deleted_by_admin:
                    message += f" Deleted by administrator (ID: {deleted_by})."
                else:
                    message += " Account was self-deleted."
                
                # Send to all admins
                await send_admin_websocket_notification(
                    title=title,
                    message=message,
                    notification_type="warning",
                    action_type="user_deleted",
                    action_data={
                        "deleted_user_id": user_id,
                        "deleted_user_email": user_email,
                        "deleted_by": deleted_by,
                        "deleted_by_admin": deleted_by_admin,
                        "deleted_at": datetime.now().isoformat()
                    }
                )
        
        asyncio.run(_send_notification())
        logger.info(f"User deletion notification sent for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in user deletion notification task: {e}")

@celery_app.task(name="send_password_change_notification")
def send_password_change_notification(user_id: int, changed_by_admin: bool = False, changed_by: int = None):
    """Celery task to send password change notification"""
    try:
        from app.database import get_db_context
        from app.services.notification_service import notification_service
        
        async def _send_notification():
            async with get_db_context() as db:
                if changed_by_admin:
                    title = "Password Reset by Administrator"
                    message = "Your password has been reset by an administrator. Please change it after logging in."
                    action_type = "password_changed_admin"
                else:
                    title = "Password Changed"
                    message = "Your password has been changed successfully."
                    action_type = "password_changed"
                
                await notification_service.create_notification(
                    db=db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type="warning",
                    action_type=action_type,
                    action_data={
                        "changed_by_admin": changed_by_admin,
                        "changed_by": changed_by or user_id,
                        "changed_at": datetime.now().isoformat()
                    }
                )
                
                # Send real-time WebSocket notification
                from app.hooks.notification_hooks import send_websocket_notification
                await send_websocket_notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type="warning",
                    action_type=action_type,
                    action_data={
                        "changed_by_admin": changed_by_admin,
                        "changed_by": changed_by or user_id
                    }
                )
        
        asyncio.run(_send_notification())
        logger.info(f"Password change notification sent for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in password change notification task: {e}")