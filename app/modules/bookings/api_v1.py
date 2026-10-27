from fastapi import APIRouter, HTTPException, status

from app.models.bookings import Booking, WaitlistEntry, WaitlistStatus
from app.modules.auth.dependencies import CurrentUser
from app.modules.bookings.dependencies import BookingServiceDependency
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.schemas import (
    BookingResponse,
    CreateBookingRequest,
    SessionWaitlistResponse,
    WaitlistResponse,
)
from app.modules.bookings.service import (
    BookingNotFoundError,
    BookingStateError,
    SessionFullError,
    SessionNotFoundError,
    WaitlistEntryNotFoundError,
    offer_deadline,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


def booking_response(booking: Booking) -> BookingResponse:
    return BookingResponse(
        id=booking.id,
        session_id=booking.session_id,
        resource_name=booking.resource_name,
        resource_type=booking.resource_type,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        status=booking.status.value,
    )


def waitlist_response(entry: WaitlistEntry) -> SessionWaitlistResponse:
    is_open = entry.status == WaitlistStatus.OFFERED and entry.offered_at is not None
    return SessionWaitlistResponse(
        id=entry.id,
        session_id=entry.session_id,
        resource_name=entry.session.resource_name,
        starts_at=entry.session.starts_at,
        status=entry.status.value,
        offered_at=entry.offered_at,
        offer_expires_at=offer_deadline(entry.offered_at, entry.session) if is_open else None,
    )


def eligibility_error(error: BookingEligibilityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=[{"code": item.code, "message": item.message} for item in error.failures],
    )


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: CreateBookingRequest, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    """Book a place on a timetable session (see GET /sessions for the session ids)."""
    try:
        return booking_response(await service.create(current_user.id, payload.session_id))
    except SessionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SessionFullError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingEligibilityError as error:
        raise eligibility_error(error) from error


@router.get("/waitlist/me", response_model=list[SessionWaitlistResponse])
async def list_my_waitlist_entries(
    current_user: CurrentUser, service: BookingServiceDependency
) -> list[SessionWaitlistResponse]:
    """The member's session waiting lists, including any place currently offered to them."""
    entries = await service.list_waitlist_for_user(current_user.id)
    return [waitlist_response(entry) for entry in entries]


@router.post(
    "/waitlist/{entry_id}/accept",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_waitlist_offer(
    entry_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    """Take up an offered place. Eligibility is checked again; a refusal ends the offer."""
    try:
        return booking_response(await service.accept_offer(current_user.id, entry_id))
    except WaitlistEntryNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingEligibilityError as error:
        raise eligibility_error(error) from error


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


@router.post("/{booking_id}/check-in", response_model=BookingResponse)
async def check_in_to_booking(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    try:
        return booking_response(await service.check_in(current_user.id, booking_id))
    except BookingNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete("/{booking_id}", response_model=BookingResponse)
async def cancel_booking(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> BookingResponse:
    try:
        return booking_response(await service.cancel(current_user.id, booking_id))
    except BookingNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
