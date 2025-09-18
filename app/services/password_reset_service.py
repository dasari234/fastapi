import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PASSWORD_RESET_BASE_URL, PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
from app.database import get_db_context
from app.models.user import PasswordResetToken, User
from app.services.auth_service import auth_service
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

class PasswordResetService:
    
    async def create_reset_token(self, email: str, db: AsyncSession = None) -> Tuple[Optional[str], int]:
        """Create a password reset token for the given email"""
        async def _create_token(session: AsyncSession) -> Tuple[Optional[str], int]:
            try:
                # Check if user exists
                result = await session.execute(
                    select(User).where(User.email == email, User.is_active == True)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    # Don't reveal if email exists or not
                    logger.info(f"Password reset requested for non-existent or inactive email: {email}")
                    return None, status.HTTP_202_ACCEPTED
                
                # Generate secure token
                token = secrets.token_urlsafe(32)
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
                
                # Create reset token record
                reset_token = PasswordResetToken(
                    email=email,
                    token=token,
                    expires_at=expires_at
                )
                
                session.add(reset_token)
                await session.commit()
                
                logger.info(f"Created password reset token for {email}")
                return token, status.HTTP_201_CREATED
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating reset token for {email}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _create_token(db)
        else:
            async with get_db_context() as session:
                return await _create_token(session)
    
    async def verify_reset_token(self, token: str, db: AsyncSession = None) -> Tuple[Optional[str], int]:
        """Verify if a reset token is valid and not expired"""
        async def _verify_token(session: AsyncSession) -> Tuple[Optional[str], int]:
            try:
                result = await session.execute(
                    select(PasswordResetToken).where(
                        PasswordResetToken.token == token,
                        PasswordResetToken.used == False
                    )
                )
                reset_token = result.scalar_one_or_none()
                
                if not reset_token:
                    return None, status.HTTP_404_NOT_FOUND
                
                # Check if token is expired
                if datetime.now(timezone.utc) > reset_token.expires_at:
                    return None, status.HTTP_410_GONE  # Gone (expired)
                
                return reset_token.email, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error verifying reset token: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _verify_token(db)
        else:
            async with get_db_context() as session:
                return await _verify_token(session)
    
    async def use_reset_token(self, token: str, db: AsyncSession = None) -> Tuple[bool, int]:
        """Mark a reset token as used"""
        async def _use_token(session: AsyncSession) -> Tuple[bool, int]:
            try:
                result = await session.execute(
                    select(PasswordResetToken).where(PasswordResetToken.token == token)
                )
                reset_token = result.scalar_one_or_none()
                
                if not reset_token:
                    return False, status.HTTP_404_NOT_FOUND
                
                reset_token.used = True
                session.add(reset_token)
                await session.commit()
                
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error using reset token: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _use_token(db)
        else:
            async with get_db_context() as session:
                return await _use_token(session)
    
    async def reset_password(self, token: str, new_password: str, db: AsyncSession = None) -> Tuple[bool, int]:
        """Reset user password using a valid token"""
        async def _reset_password(session: AsyncSession) -> Tuple[bool, int]:
            try:
                # Verify token first
                email, status_code = await self.verify_reset_token(token, session)
                if status_code != status.HTTP_200_OK or not email:
                    return False, status_code
                
                # Get user
                result = await session.execute(
                    select(User).where(User.email == email)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return False, status.HTTP_404_NOT_FOUND
                
                # Hash new password
                hashed_password = auth_service.get_password_hash(new_password)
                user.password_hash = hashed_password
                
                # Mark token as used
                await self.use_reset_token(token, session)
                
                session.add(user)
                await session.commit()
                
                logger.info(f"Password reset successfully for {email}")
                return True, status.HTTP_200_OK
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error resetting password: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _reset_password(db)
        else:
            async with get_db_context() as session:
                return await _reset_password(session)
    
    async def send_password_reset_email(self, email: str, db: AsyncSession = None) -> Tuple[bool, int]:
        """Send password reset email to user"""
        async def _send_email(session: AsyncSession) -> Tuple[bool, int]:
            try:
                logger.info(f"Attempting to send password reset email to: {email}")
                
                # Create reset token
                token, status_code = await self.create_reset_token(email, session)
                logger.info(f"Token creation result: status={status_code}, token={token is not None}")
                
                if status_code != status.HTTP_201_CREATED or not token:
                    logger.warning(f"Failed to create reset token for {email}: status={status_code}")
                    return False, status_code
                
                # Build reset link using configurable base URL
                reset_link = f"{PASSWORD_RESET_BASE_URL}?token={token}"
                logger.info(f"Generated reset link: {reset_link}")
                
                # Email content
                subject = "Password Reset Request"
                html_content = f"""
                <h2>Password Reset Request</h2>
                <p>You requested to reset your password. Click the link below to proceed:</p>
                <p><a href="{reset_link}">Reset Password</a></p>
                <p>This link will expire in {PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.</p>
                <p>If you didn't request this, please ignore this email.</p>
                """
                
                # Send email
                logger.info(f"Sending email to: {email}")
                success = await email_service.send_email(
                    to_email=email,
                    subject=subject,
                    html_content=html_content
                )
                
                if not success:
                    logger.error(f"Failed to send password reset email to {email}")
                    return False, status.HTTP_500_INTERNAL_SERVER_ERROR
                
                logger.info(f"Password reset email sent successfully to {email}")
                return True, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error sending password reset email to {email}: {e}", exc_info=True)
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        if db:
            return await _send_email(db)
        else:
            async with get_db_context() as session:
                return await _send_email(session)
            
# Create global instance
password_reset_service = PasswordResetService()

