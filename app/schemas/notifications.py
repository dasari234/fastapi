from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel


class NotificationType(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotificationCreate(BaseModel):
    title: str
    message: str
    notification_type: NotificationType = NotificationType.INFO
    metadata: Optional[Dict[str, Any]] = None


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    message: str
    notification_type: str
    is_read: bool
    metadata: Dict[str, Any]
    created_at: Optional[datetime]
    read_at: Optional[datetime]

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total_count: int
    unread_count: int