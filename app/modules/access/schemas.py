from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.access import AccessZone


class CheckInRequest(BaseModel):
    member_id: UUID | None = None
    zone: AccessZone = AccessZone.GYM_FLOOR


class AccessLogResponse(BaseModel):
    id: int
    member_id: UUID
    event: str
    zone: str
    source: str
    occurred_at: datetime


class DeviceCheckInRequest(BaseModel):
    """Sent by a door scanner after it has recognised a member's face."""

    member_id: UUID


class WaitlistPositionResponse(BaseModel):
    zone: AccessZone
    position: int | None
