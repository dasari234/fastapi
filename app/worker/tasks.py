import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from celery import shared_task
from loguru import logger

from app.database import get_db_context
from app.models.notification import Notification
from app.services import redis_service


@shared_task(bind=True, max_retries=3)
def send_notification(self, notification_id):
    """Send a notification via the appropriate channels"""
    try:
        from sqlalchemy import select, update
        
        async def _send_notification():
            async with get_db_context() as session:
                # Get notification
                result = await session.execute(
                    select(Notification).where(Notification.id == notification_id)
                )
                notification = result.scalar_one_or_none()
                
                if not notification:
                    logger.error(f"Notification {notification_id} not found")
                    return
                
                # Get user preferences
                from app.services.notification_service import notification_service
                preferences, status_code = await notification_service.get_notification_preferences(
                    notification.user_id, session
                )
                
                if status_code != 200:
                    logger.error(f"Failed to get preferences for user {notification.user_id}")
                    return
                
                sent_via = []
                
                # Send via email if enabled
                if preferences.get('email_enabled', False):
                    if await _send_email_notification(notification):
                        sent_via.append('email')
                
                # Send via push if enabled (implementation would depend on your push service)
                if preferences.get('push_enabled', False):
                    if await _send_push_notification(notification):
                        sent_via.append('push')
                
                # In-app notifications are always "sent" since they're stored in DB
                if preferences.get('in_app_enabled', True):
                    sent_via.append('in_app')
                
                # Update notification status
                if sent_via:
                    await session.execute(
                        update(Notification)
                        .where(Notification.id == notification_id)
                        .values(
                            is_sent=True,
                            sent_via=','.join(sent_via),
                            sent_at=datetime.now(timezone.utc)
                        )
                    )
                    await session.commit()
                    
                    # Also publish to Redis for real-time updates
                    await redis_service.publish_notification(
                        f"user:{notification.user_id}:notifications",
                        {
                            "type": "new_notification",
                            "data": notification.to_dict()
                        }
                    )
                
        # Run the async function
        import asyncio
        asyncio.run(_send_notification())
        
    except Exception as e:
        logger.error(f"Error sending notification {notification_id}: {e}")
        self.retry(exc=e, countdown=2 ** self.request.retries)


async def _send_email_notification(notification):
    """Send notification via email"""
    try:
        # This is a simplified example - you'd want to use a proper email service
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')
        
        # Get user email (you'd need to fetch this from the database)
        from app.services.user_service import user_service
        user_data, status_code = await user_service.get_user_by_id(notification.user_id)
        
        if status_code != 200:
            return False
        
        user_email = user_data.get('email')
        
        if not user_email:
            return False
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = user_email
        msg['Subject'] = notification.title
        
        body = f"""
        {notification.message}
        
        Action: {notification.action_type}
        Date: {notification.created_at}
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Email notification sent to {user_email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending email notification: {e}")
        return False


async def _send_push_notification(notification):
    """Send push notification"""
    # Implementation would depend on your push notification service (FCM, APNS, etc.)
    # This is a placeholder
    try:
        logger.info(f"Would send push notification: {notification.title}")
        return True
    except Exception as e:
        logger.error(f"Error sending push notification: {e}")
        return False


@shared_task
def process_batch_notifications():
    """Process batch notifications for users who prefer digests"""
    try:
        async def _process_batch():
            from datetime import datetime, timedelta, timezone

            from sqlalchemy import and_, select, update
            
            async with get_db_context() as session:
                # Get users with digest preferences
                from app.models.notification import NotificationPreference
                result = await session.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.digest_frequency != 'realtime'
                    )
                )
                preferences = result.scalars().all()
                
                for preference in preferences:
                    # Get unsent notifications for this user
                    notifications_result = await session.execute(
                        select(Notification).where(and_(
                            Notification.user_id == preference.user_id,
                            Notification.is_sent == False,
                            Notification.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                        ))
                    )
                    unsent_notifications = notifications_result.scalars().all()
                    
                    if unsent_notifications:
                        # Create digest based on frequency
                        if await _should_send_digest(preference):
                            # Send digest
                            if await _send_digest_notification(preference.user_id, unsent_notifications):
                                # Mark as sent
                                notification_ids = [n.id for n in unsent_notifications]
                                await session.execute(
                                    update(Notification)
                                    .where(Notification.id.in_(notification_ids))
                                    .values(
                                        is_sent=True,
                                        sent_via='digest',
                                        sent_at=datetime.now(timezone.utc)
                                    )
                                )
                                await session.commit()
        
        import asyncio
        asyncio.run(_process_batch())
        
    except Exception as e:
        logger.error(f"Error processing batch notifications: {e}")


async def _should_send_digest(preference):
    """Check if it's time to send a digest based on frequency"""
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    
    if preference.digest_frequency == 'hourly':
        # Send if it's the top of the hour
        return now.minute == 0
    elif preference.digest_frequency == 'daily':
        # Send at a specific time (e.g., 8 AM)
        return now.hour == 8 and now.minute == 0
    elif preference.digest_frequency == 'weekly':
        # Send on a specific day and time (e.g., Monday 8 AM)
        return now.weekday() == 0 and now.hour == 8 and now.minute == 0
    
    return False


async def _send_digest_notification(user_id, notifications):
    """Send a digest notification"""
    try:
        # Get user email
        from app.services.user_service import user_service
        user_data, status_code = await user_service.get_user_by_id(user_id)
        
        if status_code != 200:
            return False
        
        user_email = user_data.get('email')
        
        if not user_email:
            return False
        
        # Create digest content
        subject = f"Digest: {len(notifications)} notifications"
        message = f"You have {len(notifications)} new notifications:\n\n"
        
        for notification in notifications:
            message += f"- {notification.title}: {notification.message}\n"
        
        # Send email (simplified)
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')
        
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = user_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Digest notification sent to {user_email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending digest notification: {e}")
        return False
    
    