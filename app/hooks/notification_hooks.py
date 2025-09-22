from loguru import logger

from app.services import notification_service


async def notify_user_created(user_id: int, user_data: dict, db=None):
    """Send notification when a user is created"""
    try:
        title = "Welcome to the Platform!"
        message = f"Your account has been successfully created. Welcome {user_data.get('first_name', 'User')}!"
        
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="success",
            action_type="user_created",
            action_data=user_data,
            db=db
        )
        logger.info(f"User creation notification sent for user {user_id}")
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


async def notify_login(user_id: int, login_data: dict, db=None):
    """Send notification when a user logs in"""
    try:
        title = "New Login Detected"
        message = f"A new login was detected from {login_data.get('ip_address', 'unknown location')}."
        
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="user_login",
            action_data=login_data,
            db=db
        )
        logger.info(f"Login notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending login notification: {e}")
        
async def notify_profile_updated(user_id: int, user_data: dict, db=None):
    """Send notification when a user profile is updated"""
    try:
        title = "Profile Updated"
        message = "Your profile information has been successfully updated."
        
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="profile_updated",
            action_data=user_data,
            db=db
        )
        logger.info(f"Profile update notification sent for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending profile update notification: {e}")
        
async def notify_password_changed(user_id: int, user_data: dict, db=None):
    """Send notification about password change"""
    try:
        title = "Password Changed"
        message = "Your password has been successfully updated."
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="password_updated",
            action_data=user_data,
            db=db
        )
        logger.info(f"Password changed for user {user_id} ({user_data['email']})")
    except Exception as e:
        logger.error(f"Failed to send password change notification: {e}")

async def notify_password_changed_admin(user_id: int, user_data: dict, db=None):
    """Send notification about admin-initiated password change"""
    try:
        title = "Password Changed by Admin"
        message = "Your password has been successfully updated."
        await notification_service.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="info",
            action_type="password_updated_by_admin",
            action_data=user_data,
            db=db
        )
        logger.info(f"Password changed by admin for user {user_id} ({user_data['email']})")
    except Exception as e:
        logger.error(f"Failed to send admin password change notification: {e}")