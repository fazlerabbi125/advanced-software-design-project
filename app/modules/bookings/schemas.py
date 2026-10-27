from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.bookings import BookingResourceType, BookingStatus, WaitlistEntry, WaitlistStatus
from app.modules.bookings.service import offer_deadline


class CreateBookingRequest(BaseModel):
    timetable_session_id: int


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timetable_session_id: int | None
    resource_name: str
    resource_type: BookingResourceType
    starts_at: datetime
    ends_at: datetime | None
    status: BookingStatus


class SessionWaitlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    resource_name: str
    starts_at: datetime
    status: WaitlistStatus
    offered_at: datetime | None
    # Set while an offer is open: accept it before this time.
    offer_expires_at: datetime | None

    @model_validator(mode="before")
    @classmethod
    def from_waitlist_entry(cls, value: Any) -> Any:
        if not isinstance(value, WaitlistEntry):
            return value
        timetable_session = value.session
        is_open = value.status == WaitlistStatus.OFFERED and value.offered_at is not None
        return {
            "id": value.id,
            "session_id": value.session_id,
            "resource_name": timetable_session.resource_name,
            "starts_at": timetable_session.starts_at,
            "status": value.status,
            "offered_at": value.offered_at,
            "offer_expires_at": (
                offer_deadline(value.offered_at, timetable_session) if is_open else None
            ),
        }


class WaitlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    status: WaitlistStatus
