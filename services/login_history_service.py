from datetime import datetime
from typing import List, Optional, Tuple

from loguru import logger
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.login_history import LoginHistory


class LoginHistoryService:
    @staticmethod
    async def create_login_record(
        db: AsyncSession,
        user_id: int,
        ip_address: str = None,
        user_agent: str = None,
        login_status: str = "success",
        failure_reason: str = None,
    ) -> Tuple[Optional[LoginHistory], int]:
        """Create login history record with standardized response"""
        try:
            login_record = LoginHistory(
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                login_status=login_status,
                failure_reason=failure_reason,
            )
            db.add(login_record)
            await db.commit()
            await db.refresh(login_record)
            return login_record, 200
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating login record: {e}")
            return None, 500

    @staticmethod
    async def get_last_login_time(
        db: AsyncSession, user_id: int
    ) -> Tuple[Optional[datetime], int]:
        """Get the most recent successful login time for a user with standardized response"""
        try:
            result = await db.execute(
                select(LoginHistory.login_time)
                .where(
                    LoginHistory.user_id == user_id,
                    LoginHistory.login_status == "success",
                )
                .order_by(desc(LoginHistory.login_time))
                .limit(1)
            )
            last_login = result.scalar_one_or_none()
            return last_login, 200
        except Exception as e:
            logger.error(f"Error getting last login time for user {user_id}: {e}")
            return None, 500

    @staticmethod
    async def get_login_count(
        db: AsyncSession, user_id: int
    ) -> Tuple[Optional[int], int]:
        """Get total successful login count with standardized response"""
        try:
            result = await db.execute(
                select(func.count(LoginHistory.id)).where(
                    LoginHistory.user_id == user_id,
                    LoginHistory.login_status == "success",
                )
            )
            count = result.scalar() or 0
            return count, 200
        except Exception as e:
            logger.error(f"Error getting login count for user {user_id}: {e}")
            return None, 500

    @staticmethod
    async def get_user_login_history(
        db: AsyncSession, user_id: int, limit: int = 10
    ) -> Tuple[Optional[List[dict]], int]:
        """Get user login history with standardized response"""
        try:
            result = await db.execute(
                select(LoginHistory)
                .where(LoginHistory.user_id == user_id)
                .order_by(desc(LoginHistory.login_time))
                .limit(limit)
            )
            history_records = result.scalars().all()

            history_data = [
                {
                    "login_time": record.login_time.isoformat()
                    if record.login_time
                    else None,
                    "ip_address": record.ip_address,
                    "user_agent": record.user_agent,
                    "login_status": record.login_status,
                    "failure_reason": record.failure_reason,
                }
                for record in history_records
            ]

            return history_data, 200
        except Exception as e:
            logger.error(f"Error getting login history for user {user_id}: {e}")
            return None, 500

    @staticmethod
    async def get_failed_login_count(
        db: AsyncSession, user_id: int
    ) -> Tuple[Optional[int], int]:
        """Get total failed login count with standardized response"""
        try:
            result = await db.execute(
                select(func.count(LoginHistory.id)).where(
                    LoginHistory.user_id == user_id,
                    LoginHistory.login_status == "failed",
                )
            )
            count = result.scalar() or 0
            return count, 200
        except Exception as e:
            logger.error(f"Error getting failed login count for user {user_id}: {e}")
            return None, 500

    @staticmethod
    async def get_recent_failed_logins(
        db: AsyncSession, user_id: int, hours: int = 24
    ) -> Tuple[Optional[List[dict]], int]:
        """Get recent failed login attempts within specified hours"""
        try:
            from datetime import datetime, timedelta, timezone

            time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours)

            result = await db.execute(
                select(LoginHistory)
                .where(
                    LoginHistory.user_id == user_id,
                    LoginHistory.login_status == "failed",
                    LoginHistory.login_time >= time_threshold,
                )
                .order_by(desc(LoginHistory.login_time))
            )

            failed_logins = result.scalars().all()

            login_data = [
                {
                    "login_time": login.login_time.isoformat()
                    if login.login_time
                    else None,
                    "ip_address": login.ip_address,
                    "user_agent": login.user_agent,
                    "failure_reason": login.failure_reason,
                }
                for login in failed_logins
            ]

            return login_data, 200
        except Exception as e:
            logger.error(f"Error getting recent failed logins for user {user_id}: {e}")
            return None, 500


# Create global instance
login_history_service = LoginHistoryService()
