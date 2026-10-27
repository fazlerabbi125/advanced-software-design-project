from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.bookings import BookingResourceType


def check_time_range(starts_at: datetime, ends_at: datetime) -> None:
    for value in (starts_at, ends_at):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at and ends_at must include a timezone offset")
    if ends_at <= starts_at:
        raise ValueError("ends_at must be after starts_at")


class CreateSessionRequest(BaseModel):
    # For an equipment slot the unit's name is used instead.
    resource_name: str = Field(min_length=1, max_length=150)
    resource_type: BookingResourceType
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0)
    station_count: int | None = Field(default=None, gt=0)
    equipment_unit_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_times(self) -> "CreateSessionRequest":
        check_time_range(self.starts_at, self.ends_at)
        is_equipment = self.resource_type == BookingResourceType.EQUIPMENT
        if is_equipment != (self.equipment_unit_id is not None):
            raise ValueError("equipment slots, and only equipment slots, need an equipment_unit_id")
        if is_equipment and self.capacity != 1:
            raise ValueError("an equipment slot is for one member, so capacity must be 1")
        return self


class GenerateEquipmentSlotsRequest(BaseModel):
    """Back-to-back slots on one unit, e.g. every 30 minutes from 06:00 to 22:00."""

    equipment_unit_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    slot_minutes: int = Field(ge=15, le=240)

    @model_validator(mode="after")
    def check_times(self) -> "GenerateEquipmentSlotsRequest":
        check_time_range(self.starts_at, self.ends_at)
        if self.ends_at - self.starts_at > timedelta(days=1):
            raise ValueError("generate at most one day of slots at a time")
        if self.ends_at - self.starts_at < timedelta(minutes=self.slot_minutes):
            raise ValueError("the range is shorter than one slot")
        return self


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_name: str
    resource_type: BookingResourceType
    starts_at: datetime
    ends_at: datetime
    capacity: int
    allocated_count: int
    spots_left: int
    station_count: int | None
    equipment_unit_id: int | None
