from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.access import AccessZone


class CheckInRequest(BaseModel):
    member_id: int | None = Field(default=None, gt=0)
    zone: AccessZone = AccessZone.GYM_FLOOR


class ManualCheckInRequest(BaseModel):
    """Sent by staff after they have verified the member's identity themselves."""

    member_id: int = Field(gt=0)
    zone: AccessZone = AccessZone.GYM_FLOOR
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class AccessLogResponse(BaseModel):
    id: int
    member_id: int
    event: str
    zone: str
    source: str
    occurred_at: datetime
    performed_by_staff_id: int | None = None
    staff_reason: str | None = None


class DeviceCheckInRequest(BaseModel):
    """Sent by a door scanner after it has recognised a member's face."""

    member_id: int = Field(gt=0)


class WaitlistPositionResponse(BaseModel):
    zone: AccessZone
    position: int | None
