from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime
from models.schemas import LoginHistory

class LoginHistoryService:
    @staticmethod
    async def create_login_record(
        db: AsyncSession, 
        user_id: int, 
        ip_address: str = None, 
        user_agent: str = None,
        login_status: str = "success",
        failure_reason: str = None
    ) -> LoginHistory:
        login_record = LoginHistory(
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            login_status=login_status,
            failure_reason=failure_reason
        )
        db.add(login_record)
        await db.commit()
        await db.refresh(login_record)
        return login_record
    
    @staticmethod
    async def get_last_login_time(db: AsyncSession, user_id: int) -> datetime:
        """Get the most recent successful login time for a user"""
        result = await db.execute(
            select(LoginHistory.login_time)
            .where(
                LoginHistory.user_id == user_id,
                LoginHistory.login_status == "success"
            )
            .order_by(desc(LoginHistory.login_time))
            .limit(1)
        )
        last_login = result.scalar_one_or_none()
        return last_login
    
    @staticmethod
    async def get_user_login_history(
        db: AsyncSession, 
        user_id: int, 
        limit: int = 10
    ) -> list[LoginHistory]:
        result = await db.execute(
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(desc(LoginHistory.login_time))
            .limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_login_count(db: AsyncSession, user_id: int) -> int:
        """Get total successful login count"""
        result = await db.execute(
            select(LoginHistory)
            .where(
                LoginHistory.user_id == user_id,
                LoginHistory.login_status == "success"
            )
        )
        return len(result.scalars().all())

# Create global instance
login_history_service = LoginHistoryService()