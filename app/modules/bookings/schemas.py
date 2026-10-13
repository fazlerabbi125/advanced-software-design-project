from datetime import datetime

from pydantic import BaseModel, Field

from app.models.bookings import BookingResourceType


class CreateBookingRequest(BaseModel):
    resource_name: str = Field(min_length=1, max_length=150)
    resource_type: BookingResourceType
    starts_at: datetime


class BookingResponse(BaseModel):
    id: int
    resource_name: str
    resource_type: BookingResourceType
    starts_at: datetime
    status: str


class WaitlistResponse(BaseModel):
    id: int
    booking_id: int
    status: str
