from fastapi import APIRouter, HTTPException, status

from app.models.bookings import Booking
from app.modules.auth.dependencies import CurrentUser
from app.modules.bookings.dependencies import BookingServiceDependency
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.schemas import BookingResponse, CreateBookingRequest, WaitlistResponse

router = APIRouter(prefix="/bookings", tags=["bookings"])


def booking_response(booking: Booking) -> BookingResponse:
    return BookingResponse(
        id=booking.id,
        resource_name=booking.resource_name,
        resource_type=booking.resource_type,
        starts_at=booking.starts_at,
        status=booking.status.value,
    )


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: CreateBookingRequest, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    try:
        return booking_response(
            await service.create(
                current_user.id,
                payload.resource_name,
                payload.resource_type,
                payload.starts_at,
            )
        )
    except BookingEligibilityError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"code": item.code, "message": item.message} for item in error.failures],
        ) from error
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
