from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(50), nullable=False)  # info, success, warning, error
    action_type = Column(String(100), nullable=False)  # user_created, file_uploaded, file_deleted, etc.
    action_data = Column(JSON, nullable=True)  # Additional data about the action
    is_read = Column(Boolean, default=False, index=True)
    is_sent = Column(Boolean, default=False, index=True)
    sent_via = Column(String(50), nullable=True)  # email, websocket, push, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship to user
    user = relationship("User", back_populates="notifications")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "message": self.message,
            "type": self.notification_type,
            "action_type": self.action_type,
            "action_data": self.action_data or {},
            "is_read": self.is_read,
            "is_sent": self.is_sent,
            "sent_via": self.sent_via,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    email_enabled = Column(Boolean, default=True)
    push_enabled = Column(Boolean, default=False)
    in_app_enabled = Column(Boolean, default=True)
    digest_frequency = Column(String(20), default="realtime")  # realtime, hourly, daily, weekly
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship to user
    user = relationship("User", back_populates="notification_preferences")
    
    