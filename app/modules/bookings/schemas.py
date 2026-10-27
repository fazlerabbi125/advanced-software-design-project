from datetime import datetime

from pydantic import BaseModel

from app.models.bookings import BookingResourceType


class CreateBookingRequest(BaseModel):
    timetable_session_id: int


class BookingResponse(BaseModel):
    id: int
    timetable_session_id: int | None
    resource_name: str
    resource_type: BookingResourceType
    starts_at: datetime
    ends_at: datetime | None
    status: str


class SessionWaitlistResponse(BaseModel):
    id: int
    session_id: int
    resource_name: str
    starts_at: datetime
    status: str
    offered_at: datetime | None
    # Set while an offer is open: accept it before this time.
    offer_expires_at: datetime | None


class WaitlistResponse(BaseModel):
    id: int
    booking_id: int
    status: str
