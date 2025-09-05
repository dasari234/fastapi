from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON, Enum, CheckConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import enum
from datetime import datetime

Base = declarative_base()

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user', 'moderator')", name="check_user_role"),
        CheckConstraint("email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$'", name="valid_email"),
        Index('idx_users_email', 'email'),
        Index('idx_users_role', 'role'),
        Index('idx_users_active', 'is_active'),
        Index('idx_users_created_at', 'created_at'),
    )

class Book(Base):
    __tablename__ = "books"
    
    book_id = Column(String(32), primary_key=True)
    name = Column(String(255), nullable=False)
    genre = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("genre IN ('fiction', 'non-fiction')", name="check_book_genre"),
        CheckConstraint("price > 0", name="check_book_price"),
        Index('idx_books_genre', 'genre'),
        Index('idx_books_price', 'price'),
        Index('idx_books_created_at', 'created_at'),
    )

class FileUpload(Base):
    __tablename__ = "file_uploads"
    
    id = Column(Integer, primary_key=True)
    original_filename = Column(String(255), nullable=False)
    s3_key = Column(String(500), unique=True, nullable=False)
    s3_url = Column(String(1000), nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False)
    folder_path = Column(String(255))
    file_content = Column(Text)
    score = Column(Float, default=0.0)
    upload_status = Column(String(20), default='success')
    error_message = Column(Text)
    user_id = Column(String(100))
    metadata = Column(JSON)
    upload_ip = Column(String(45))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="check_file_size"),
        CheckConstraint("score >= 0 AND score <= 100", name="check_score_range"),
        CheckConstraint("upload_status IN ('success', 'failed', 'processing', 'error')", name="check_upload_status"),
        CheckConstraint("original_filename !~ '[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F-\\x9F]'", name="check_filename_clean"),
        CheckConstraint("LENGTH(TRIM(original_filename)) > 0", name="check_no_empty_filename"),
        CheckConstraint("s3_key ~ '^[a-zA-Z0-9._/-]+$'", name="check_s3_key_format"),
        Index('idx_file_uploads_s3_key', 's3_key'),
        Index('idx_file_uploads_user_id', 'user_id'),
        Index('idx_file_uploads_created_at', 'created_at'),
        Index('idx_file_uploads_folder', 'folder_path'),
        Index('idx_file_uploads_status', 'upload_status'),
        Index('idx_file_uploads_size', 'file_size'),
        Index('idx_file_uploads_content_type', 'content_type'),
    )