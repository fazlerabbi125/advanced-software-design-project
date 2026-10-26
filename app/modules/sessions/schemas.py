from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.bookings import BookingResourceType


class CreateSessionRequest(BaseModel):
    resource_name: str = Field(min_length=1, max_length=150)
    resource_type: BookingResourceType
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0)
    station_count: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_times(self) -> "CreateSessionRequest":
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("starts_at and ends_at must include a timezone offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class SessionResponse(BaseModel):
    id: int
    resource_name: str
    resource_type: BookingResourceType
    starts_at: datetime
    ends_at: datetime
    capacity: int
    allocated_count: int
    spots_left: int
    station_count: int | None
