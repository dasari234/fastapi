from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey,
                        Index, Integer, String, Text, func)
from sqlalchemy.orm import relationship

from schemas.base import Base


class FileUploadRecord(Base):
    __tablename__ = "file_uploads"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    s3_key = Column(String(512), unique=True, index=True, nullable=False)
    s3_url = Column(Text, nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False)
    file_content = Column(Text, nullable=True)
    score = Column(Float, default=0.0)
    folder_path = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    file_metadata = Column(JSON, nullable=True)
    upload_ip = Column(String(45), nullable=True)
    upload_status = Column(String(20), default="success", nullable=False)

    processing_time_ms = Column(Float, default=0.0)
    version = Column(Integer, default=1, nullable=False)
    is_current_version = Column(Boolean, default=True, nullable=False)
    parent_version_id = Column(
        Integer, ForeignKey("file_uploads.id", ondelete="SET NULL"), nullable=True
    )
    version_comment = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # REMOVE THIS LINE - it conflicts with the relationship in User class
    # uploading_user = relationship("User", back_populates="file_uploads")

    # Index for better performance
    __table_args__ = (
        Index("ix_file_upload_user_id", "user_id"),
        Index("ix_file_upload_s3_key", "s3_key"),
        Index("ix_file_upload_version", "version"),
        Index("ix_file_upload_current_version", "is_current_version"),
        Index("ix_file_upload_s3_key_version", "s3_key", "version", unique=True),
        Index("ix_file_upload_created_at", "created_at"),
        Index("ix_file_upload_parent_version", "parent_version_id"),
    )

    # Relationship to parent version (self-referential)
    parent_version = relationship(
        "FileUploadRecord",
        foreign_keys=[parent_version_id],
        remote_side=[id],
        backref="child_versions",
    )

    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "s3_key": self.s3_key,
            "s3_url": self.s3_url,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "score": self.score,
            "folder_path": self.folder_path,
            "user_id": self.user_id,
            "upload_ip": self.upload_ip,
            "upload_status": self.upload_status,
            "processing_time_ms": self.processing_time_ms,
            "version": self.version,
            "is_current_version": self.is_current_version,
            "parent_version_id": self.parent_version_id,
            "version_comment": self.version_comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "has_content": bool(self.file_content),
            "metadata": self.file_metadata or {}
        }
  