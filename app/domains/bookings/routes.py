from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser
from app.domains.bookings.dependencies import BookingServiceDependency
from app.models.bookings import Booking

router = APIRouter(prefix="/bookings", tags=["bookings"])


class CreateBookingRequest(BaseModel):
    resource_name: str = Field(min_length=1, max_length=150)
    starts_at: datetime


class BookingResponse(BaseModel):
    id: int
    resource_name: str
    starts_at: datetime
    status: str


class WaitlistResponse(BaseModel):
    id: int
    booking_id: int
    status: str


def booking_response(booking: Booking) -> BookingResponse:
    return BookingResponse(
        id=booking.id,
        resource_name=booking.resource_name,
        starts_at=booking.starts_at,
        status=booking.status.value,
    )


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: CreateBookingRequest, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    try:
        return booking_response(
            await service.create(current_user.id, payload.resource_name, payload.starts_at)
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error


@router.get("/me", response_model=list[BookingResponse])
async def list_my_bookings(
    current_user: CurrentUser, service: BookingServiceDependency
) -> list[BookingResponse]:
    return [booking_response(booking) for booking in await service.list_for_user(current_user.id)]


@router.post(
    "/{booking_id}/waitlist", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED
)
async def join_waitlist(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> WaitlistResponse:
    try:
        entry = await service.join_waitlist(current_user.id, booking_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return WaitlistResponse(id=entry.id, booking_id=entry.booking_id, status=entry.status.value)


@router.delete("/{booking_id}", response_model=BookingResponse)
async def cancel_booking(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    try:
        return booking_response(await service.cancel(current_user.id, booking_id))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
