from datetime import datetime

from pydantic import BaseModel, Field

from app.models.access import AccessZone


class CheckInRequest(BaseModel):
    member_id: int | None = Field(default=None, gt=0)
    zone: AccessZone = AccessZone.GYM_FLOOR


class AccessLogResponse(BaseModel):
    id: int
    member_id: int
    event: str
    zone: str
    source: str
    occurred_at: datetime
