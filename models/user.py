from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from schemas.base import Base


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

