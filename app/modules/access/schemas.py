from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.access import AccessZone


class CheckInRequest(BaseModel):
    member_id: UUID | None = None
    zone: AccessZone = AccessZone.GYM_FLOOR


class ManualCheckInRequest(BaseModel):
    """Sent by staff after they have verified the member's identity themselves."""

    member_id: UUID
    zone: AccessZone = AccessZone.GYM_FLOOR
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class AccessLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_id: UUID
    event: str
    zone: str
    source: str
    occurred_at: datetime
    performed_by_staff_id: UUID | None = None
    staff_reason: str | None = None


class DeviceCheckInRequest(BaseModel):
    """Sent by a door scanner after it has recognised a member's face."""

    template_id: UUID
    confidence: float = Field(ge=0, le=1)


class WaitlistPositionResponse(BaseModel):
    zone: AccessZone
    position: int | None
