from datetime import datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.notifications import NotificationType
from app.services.notification_service import notification_service
from app.services.notification_tasks import (
    send_password_change_notification,
    send_user_created_notification,
    send_user_deleted_notification,
    send_user_updated_notification,
)
from app.services.websocket_manager import websocket_manager

# =============================================================================
# USER MANAGEMENT NOTIFICATIONS (Handled by Celery tasks)
# =============================================================================

async def notify_user_created(user_id: int, user_data: dict):
    """Send notification about user creation via Celery task"""
    try:
        # Delegate to Celery task for background processing
        send_user_created_notification.delay(user_id, user_data)
        logger.debug(f"User creation notification queued for user {user_id}")
    except Exception as e:
        logger.error(f"Error queueing user creation notification: {e}")


async def notify_user_updated(user_id: int, updated_fields: dict, updated_by: int):
    """Send notification about user update via Celery task"""
    try:
        # Delegate to Celery task for background processing
        send_user_updated_notification.delay(user_id, updated_fields, updated_by)
        logger.debug(f"User update notification queued for user {user_id}")
    except Exception as e:
        logger.error(f"Error queueing user update notification: {e}")


async def notify_user_deleted(user_id: int, user_email: str, deleted_by: int, deleted_by_admin: bool = False):
    """Send notification about user deletion via Celery task"""
    try:
        # Delegate to Celery task for background processing
        send_user_deleted_notification.delay(user_id, user_email, deleted_by, deleted_by_admin)
        logger.debug(f"User deletion notification queued for user {user_id}")
    except Exception as e:
        logger.error(f"Error queueing user deletion notification: {e}")


async def notify_password_changed(user_id: int, changed_by_admin: bool = False, changed_by: int = None):
    """Send notification about password change via Celery task"""
    try:
        # Delegate to Celery task for background processing
        send_password_change_notification.delay(user_id, changed_by_admin, changed_by)
        logger.debug(f"Password change notification queued for user {user_id}")
    except Exception as e:
        logger.error(f"Error queueing password change notification: {e}")


# =============================================================================
# FILE OPERATION NOTIFICATIONS (Immediate processing)
# =============================================================================

async def notify_file_uploaded(user_id: int, file_data: dict, db: AsyncSession = None):
    """Send notification when a file is uploaded with WebSocket"""
    try:
        filename = file_data.get('original_filename', 'Unknown file')
        file_size = file_data.get('file_size', 0)
        size_display = format_file_size(file_size)
        
        title = "File Uploaded Successfully"
        message = f"Your file '{filename}' ({size_display}) has been uploaded successfully."
        
        # Create notification in database
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="success",
            action_type="file_uploaded",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key"),
                "content_type": file_data.get("content_type"),
                "uploaded_at": datetime.now().isoformat()
            },
            db=db
        )
        
        # Send real-time WebSocket notification
        await send_websocket_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="success",
            action_type="file_uploaded",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key")
            }
        )
        
        # Notify admins about file upload
        await send_admin_websocket_notification(
            title="New File Upload",
            message=f"User {user_id} uploaded '{filename}' ({size_display})",
            notification_type="info",
            action_type="file_uploaded_admin",
            action_data={
                "user_id": user_id,
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key"),
                "uploaded_at": datetime.now().isoformat()
            }
        )
        
        logger.info(f"File upload notification sent for user {user_id}, file: {filename}")
        
    except Exception as e:
        logger.error(f"Error sending file upload notification: {e}")


async def notify_file_deleted(user_id: int, file_data: dict, db: AsyncSession = None):
    """Send notification when a file is deleted with WebSocket"""
    try:
        filename = file_data.get('original_filename', 'Unknown file')
        file_size = file_data.get('file_size', 0)
        size_display = format_file_size(file_size)
        
        title = "File Deleted"
        message = f"Your file '{filename}' ({size_display}) has been deleted."
        
        # Create notification in database
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="file_deleted",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key"),
                "deleted_at": datetime.now().isoformat()
            },
            db=db
        )
        
        # Send real-time WebSocket notification
        await send_websocket_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="file_deleted",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key")
            }
        )
        
        # Notify admins about file deletion
        await send_admin_websocket_notification(
            title="File Deleted",
            message=f"User {user_id} deleted '{filename}' ({size_display})",
            notification_type="warning",
            action_type="file_deleted_admin",
            action_data={
                "user_id": user_id,
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key"),
                "deleted_at": datetime.now().isoformat()
            }
        )
        
        logger.info(f"File deletion notification sent for user {user_id}, file: {filename}")
        
    except Exception as e:
        logger.error(f"Error sending file deletion notification: {e}")


async def notify_file_download(user_id: int, file_data: dict, db: AsyncSession = None):
    """Send notification when a file is downloaded"""
    try:
        filename = file_data.get('original_filename', 'Unknown file')
        file_size = file_data.get('file_size', 0)
        size_display = format_file_size(file_size)
        
        title = "File Downloaded"
        message = f"Your file '{filename}' ({size_display}) has been downloaded."
        
        # Create notification in database
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="file_downloaded",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key"),
                "downloaded_at": datetime.now().isoformat()
            },
            db=db
        )
        
        logger.info(f"File download notification sent for user {user_id}, file: {filename}")
        
    except Exception as e:
        logger.error(f"Error sending file download notification: {e}")


# =============================================================================
# SECURITY & ACTIVITY NOTIFICATIONS
# =============================================================================

async def notify_login(user_id: int, login_data: dict, db: AsyncSession):
    """Send notification about user login with WebSocket"""
    try:
        ip_address = login_data.get('ip_address', 'Unknown')
        user_agent = login_data.get('user_agent', 'Unknown device')
        location = login_data.get('location', 'Unknown location')
        
        title = "New Login Detected"
        message = f"Your account was accessed from {ip_address} ({location}) using {user_agent}."
        
        await notification_service.create_notification(
            db=db,
            user_id=user_id,
            title=title,
            message=message,
            notification_type=NotificationType.INFO,
            action_type="user_login",
            action_data={
                "ip_address": ip_address,
                "user_agent": user_agent,
                "location": location,
                "login_time": datetime.now().isoformat()
            }
        )
        
        # Send real-time WebSocket notification
        await send_websocket_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="user_login",
            action_data={
                "ip_address": ip_address,
                "location": location,
                "user_agent": user_agent
            }
        )
        
        logger.debug(f"Login notification sent for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending login notification: {e}")


async def notify_suspicious_activity(user_id: int, activity_data: dict, db: AsyncSession = None):
    """Send notification about suspicious activity"""
    try:
        title = "Suspicious Activity Detected"
        message = activity_data.get('message', 'Unusual activity detected on your account.')
        
        await notification_service.create_notification(
            db=db,
            user_id=user_id,
            title=title,
            message=message,
            notification_type="warning",
            action_type="suspicious_activity",
            action_data=activity_data
        )
        
        # Send real-time WebSocket notification
        await send_websocket_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="warning",
            action_type="suspicious_activity",
            action_data=activity_data
        )
        
        # Also notify admins about suspicious activity
        await send_admin_websocket_notification(
            title="Suspicious User Activity",
            message=f"Suspicious activity detected for user {user_id}: {message}",
            notification_type="warning",
            action_type="suspicious_activity_admin",
            action_data={
                "user_id": user_id,
                **activity_data
            }
        )
        
        logger.warning(f"Suspicious activity notification sent for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending suspicious activity notification: {e}")


# =============================================================================
# FILE DOWNLOAD/VIEW URL NOTIFICATIONS
# =============================================================================

async def send_download_notification(
    db: AsyncSession,
    user_id: int,
    file_record: dict,
    ip_address: str = None,
    user_agent: str = None
):
    """Send notification when a download URL is generated"""
    try:
        filename = file_record.get("original_filename", "Unknown file")
        file_size = file_record.get("file_size", 0)
        file_type = get_file_type_category(file_record.get("content_type", ""))
        
        # Format file size for display
        size_display = format_file_size(file_size)
        
        # Create notification message
        title = f"{file_type} Download Ready"
        message = f"Download URL generated for '{filename}' ({size_display})"
        
        # Create notification in database
        await notification_service.create_notification(
            db=db,
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="file_download_generated",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_type": file_type,
                "file_id": file_record.get("id"),
                "s3_key": file_record.get("s3_key"),
                "content_type": file_record.get("content_type"),
                "generated_at": datetime.now().isoformat(),
                "ip_address": ip_address,
                "user_agent": user_agent
            }
        )
        
        # Send real-time WebSocket notification
        await send_file_websocket_notification(
            user_id=user_id,
            title=title,
            message=message,
            action_type="file_download_generated",
            file_data=file_record,
            ip_address=ip_address,
            additional_data={
                "file_type": file_type,
                "file_size_display": size_display
            }
        )
        
        logger.info(f"Download notification sent for user {user_id}, file: {filename}")
        
    except Exception as e:
        logger.error(f"Error sending download notification: {e}")


async def send_view_notification(
    db: AsyncSession,
    user_id: int,
    file_record: dict,
    ip_address: str = None,
    user_agent: str = None
):
    """Send notification when a view URL is generated"""
    try:
        filename = file_record.get("original_filename", "Unknown file")
        file_size = file_record.get("file_size", 0)
        file_type = get_file_type_category(file_record.get("content_type", ""))
        
        # Format file size for display
        size_display = format_file_size(file_size)
        
        # Create notification message
        title = f"{file_type} View Ready"
        message = f"View URL generated for '{filename}' ({size_display})"
        
        # Create notification in database
        await notification_service.create_notification(
            db=db,
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="file_view_generated",
            action_data={
                "filename": filename,
                "file_size": file_size,
                "file_size_display": size_display,
                "file_type": file_type,
                "file_id": file_record.get("id"),
                "s3_key": file_record.get("s3_key"),
                "content_type": file_record.get("content_type"),
                "generated_at": datetime.now().isoformat(),
                "ip_address": ip_address,
                "user_agent": user_agent
            }
        )
        
        # Send real-time WebSocket notification
        await send_file_websocket_notification(
            user_id=user_id,
            title=title,
            message=message,
            action_type="file_view_generated",
            file_data=file_record,
            ip_address=ip_address,
            additional_data={
                "file_type": file_type,
                "file_size_display": size_display
            }
        )
        
        logger.info(f"View notification sent for user {user_id}, file: {filename}")
        
    except Exception as e:
        logger.error(f"Error sending view notification: {e}")

    async def send_view_notification(
        db: AsyncSession,
        user_id: int,
        file_record: dict,
        ip_address: str = None,
        user_agent: str = None
    ):
        """Send notification when a view URL is generated"""
        try:
            logger.info(f"Starting view notification for user {user_id}, file: {file_record.get('original_filename')}")
            
            filename = file_record.get("original_filename", "Unknown file")
            file_size = file_record.get("file_size", 0)
            file_type = get_file_type_category(file_record.get("content_type", ""))
            
            # Format file size for display
            size_display = format_file_size(file_size)
            
            # Create notification message
            title = f"{file_type} View Ready"
            message = f"View URL generated for '{filename}' ({size_display})"
            
            logger.debug(f"Creating view notification: {title} - {message}")
            
            # Create notification in database
            notification_result = await notification_service.create_notification(
                db=db,
                user_id=user_id,
                title=title,
                message=message,
                notification_type="info",
                action_type="file_view_generated",
                action_data={
                    "filename": filename,
                    "file_size": file_size,
                    "file_size_display": size_display,
                    "file_type": file_type,
                    "file_id": file_record.get("id"),
                    "s3_key": file_record.get("s3_key"),
                    "content_type": file_record.get("content_type"),
                    "generated_at": datetime.now().isoformat(),
                    "ip_address": ip_address,
                    "user_agent": user_agent
                }
            )
            
            logger.debug(f"Notification creation result: {notification_result}")
            
            # Send real-time WebSocket notification
            await send_file_websocket_notification(
                user_id=user_id,
                title=title,
                message=message,
                action_type="file_view_generated",
                file_data=file_record,
                ip_address=ip_address,
                additional_data={
                    "file_type": file_type,
                    "file_size_display": size_display
                }
            )
            
            logger.info(f"View notification completed for user {user_id}, file: {filename}")
            
        except Exception as e:
            logger.error(f"Error in send_view_notification: {e}", exc_info=True)
            
# =============================================================================
# SYSTEM & ADMIN NOTIFICATIONS
# =============================================================================

# async def notify_system_alert(message: str, alert_type: str = "info", target_user_id: int = None):
#     """Send system-wide alert notification (Admin only)"""
#     try:
#         title = "System Alert"
#         if alert_type == "warning":
#             title = "System Warning"
#         elif alert_type == "error":
#             title = "System Error"
#         elif alert_type == "success":
#             title = "System Update"
        
#         # If target_user_id is provided, send to specific user, otherwise send to all admins
#         if target_user_id:
#             await send_websocket_notification(
#                 user_id=target_user_id,
#                 title=title,
#                 message=message,
#                 notification_type=alert_type,
#                 action_type="system_alert"
#             )
#         else:
#             # Send to all admin users
#             await send_admin_websocket_notification(
#                 title=title,
#                 message=message,
#                 notification_type=alert_type,
#                 action_type="system_alert"
#             )
            
#         logger.info(f"System alert sent: {message}")
#     except Exception as e:
#         logger.error(f"Error sending system alert: {e}")


# async def notify_new_user_registered(admin_user_id: int, new_user_data: dict):
#     """Notify admin when a new user registers"""
#     try:
#         user_email = new_user_data.get('email', 'Unknown')
#         user_name = f"{new_user_data.get('first_name', '')} {new_user_data.get('last_name', '')}".strip()
        
#         message = f"New user registered: {user_email}"
#         if user_name:
#             message += f" ({user_name})"
        
#         await send_websocket_notification(
#             user_id=admin_user_id,
#             title="New User Registration",
#             message=message,
#             notification_type="info",
#             action_type="new_user_registered",
#             action_data=new_user_data
#         )
        
#         logger.info(f"New user registration notification sent to admin {admin_user_id}")
#     except Exception as e:
#         logger.error(f"Error sending new user registration notification: {e}")


# async def notify_user_activity(user_id: int, activity_type: str, activity_data: dict):
#     """Notify about user activity (for admins)"""
#     try:
#         title = f"User Activity: {activity_type.replace('_', ' ').title()}"
#         message = f"User {user_id} performed {activity_type}"
        
#         # Send to all admins
#         await send_admin_websocket_notification(
#             title=title,
#             message=message,
#             notification_type="info",
#             action_type="user_activity",
#             action_data={
#                 "user_id": user_id,
#                 "activity_type": activity_type,
#                 **activity_data
#             }
#         )
        
#         logger.debug(f"User activity notification sent for user {user_id}, activity: {activity_type}")
#     except Exception as e:
#         logger.error(f"Error sending user activity notification: {e}")


# =============================================================================
# WEBSOCKET NOTIFICATION FUNCTIONS
# =============================================================================

async def send_websocket_notification(
    user_id: int,
    title: str,
    message: str,
    notification_type: str,
    action_type: str,
    action_data: dict = None,
    metadata: dict = None
):
    """Send real-time notification via WebSocket to specific user"""
    try:
        notification_data = {
            "id": f"ws_{datetime.now().timestamp()}",
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": notification_type,
            "action_type": action_type,
            "action_data": action_data or {},
            "metadata": metadata or {},
            "is_read": False,
            "created_at": datetime.now().isoformat(),
            "is_realtime": True
        }
        
        # Send to specific user
        await websocket_manager.send_personal_message({
            "type": "notification",
            "data": notification_data
        }, user_id)
        
        logger.debug(f"WebSocket notification sent to user {user_id}")
    except Exception as e:
        logger.error(f"Error sending WebSocket notification to user {user_id}: {e}")

async def send_admin_websocket_notification(
    title: str,
    message: str,
    notification_type: str,
    action_type: str,
    action_data: dict = None,
    metadata: dict = None
):
    """Send real-time notification via WebSocket to all admin users"""
    try:
        notification_data = {
            "id": f"admin_ws_{datetime.now().timestamp()}",
            "title": title,
            "message": message,
            "type": notification_type,
            "action_type": action_type,
            "action_data": action_data or {},
            "metadata": metadata or {},
            "is_read": False,
            "created_at": datetime.now().isoformat(),
            "is_realtime": True,
            "is_admin_notification": True
        }
        
        # Send to all admin users
        await websocket_manager.broadcast_to_admins({
            "type": "admin_notification",
            "data": notification_data
        })
        
        logger.debug("Admin WebSocket notification broadcasted")
    except Exception as e:
        logger.error(f"Error sending admin WebSocket notification: {e}")

async def send_file_websocket_notification(
    user_id: int,
    title: str,
    message: str,
    action_type: str,
    file_data: dict,
    ip_address: str = None,
    additional_data: dict = None
):
    """Send real-time file notification via WebSocket"""
    try:
        notification_data = {
            "id": f"file_{datetime.now().timestamp()}",
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": "info",
            "action_type": action_type,
            "action_data": {
                "filename": file_data.get("original_filename"),
                "file_size": file_data.get("file_size"),
                "file_size_display": format_file_size(file_data.get("file_size", 0)),
                "file_id": file_data.get("id"),
                "s3_key": file_data.get("s3_key"),
                "content_type": file_data.get("content_type"),
                "file_type": get_file_type_category(file_data.get("content_type", "")),
                "ip_address": ip_address,
                "timestamp": datetime.now().isoformat(),
                **(additional_data or {})
            },
            "is_read": False,
            "created_at": datetime.now().isoformat(),
            "is_realtime": True
        }
        
        # Send to specific user
        await websocket_manager.send_personal_message({
            "type": "notification",
            "data": notification_data
        }, user_id)
        
        # Also send to admins for monitoring
        admin_notification_data = {
            **notification_data,
            "target_user_id": user_id,
            "is_admin_notification": True
        }
        await websocket_manager.broadcast_to_admins({
            "type": "admin_notification",
            "data": admin_notification_data
        })
        
    except Exception as e:
        logger.error(f"Error sending file WebSocket notification: {e}")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def get_file_type_category(content_type: str) -> str:
    """Categorize file type for better notification display"""
    if not content_type:
        return "File"
    
    content_type = content_type.lower()
    
    if any(ext in content_type for ext in ['image', 'jpeg', 'png', 'gif', 'bmp', 'webp']):
        return "Image"
    elif any(ext in content_type for ext in ['video', 'mp4', 'avi', 'mov', 'mkv', 'webm']):
        return "Video"
    elif any(ext in content_type for ext in ['audio', 'mp3', 'wav', 'ogg', 'flac']):
        return "Audio"
    elif any(ext in content_type for ext in ['pdf']):
        return "PDF"
    elif any(ext in content_type for ext in ['document', 'word', 'excel', 'powerpoint', 'msword', 'vnd.openxmlformats']):
        return "Document"
    elif any(ext in content_type for ext in ['text', 'plain', 'csv', 'json', 'xml']):
        return "Text"
    elif any(ext in content_type for ext in ['zip', 'tar', 'gzip', 'rar', '7z']):
        return "Archive"
    elif any(ext in content_type for ext in ['code', 'javascript', 'python', 'java', 'cpp', 'html', 'css']):
        return "Code"
    else:
        return "File"

  
