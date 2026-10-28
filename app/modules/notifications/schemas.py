from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.notifications import NotificationType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: NotificationType
    payload: dict[str, Any]
    is_read: bool
    created_at: datetime
    read_at: datetime | None
