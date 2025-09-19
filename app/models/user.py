
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, func
from sqlalchemy.orm import relationship

from app.schemas.base import Base


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    login_history = relationship("LoginHistory", back_populates="user", cascade="all, delete-orphan")
    
    # Use consistent naming - remove overlaps parameter if not needed
    uploaded_files = relationship(
        "FileUploadRecord", 
        backref="uploader_user",
        foreign_keys="FileUploadRecord.user_id"
    )
    
    file_action_history = relationship(
        "FileHistory", 
        backref="action_user",
        foreign_keys="FileHistory.action_by"
    )
    
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    notification_preferences = relationship("NotificationPreference", back_populates="user", 
                                          uselist=False, cascade="all, delete-orphan")


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"
    
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(500), unique=True, index=True, nullable=False)
    blacklisted_at = Column(DateTime(timezone=True), nullable=False)
    
    def __repr__(self):
        return f"<TokenBlacklist {self.token}>"

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(100), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Index for better performance
    __table_args__ = (
        Index("ix_reset_token_token", "token"),
        Index("ix_reset_token_email", "email"),
        Index("ix_reset_token_expires", "expires_at"),
    )
    
    