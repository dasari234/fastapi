from sqlalchemy import (JSON, Column, DateTime, ForeignKey, Integer, String,
                        Text, func)
from sqlalchemy.orm import relationship

from app.schemas.base import Base


class FileHistory(Base):
    __tablename__ = "file_history"
    
    id = Column(Integer, primary_key=True, index=True)
    file_upload_id = Column(Integer, ForeignKey("file_uploads.id", ondelete="CASCADE"))
    s3_key = Column(String(500), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    
    # Ensure this is Integer to match User.id
    action_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    action_details = Column(JSON)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    file_upload = relationship("FileUploadRecord", backref="history_records")
   
   
   