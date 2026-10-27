from typing import Any

from fastapi import APIRouter, HTTPException, status

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
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


def eligibility_error(error: BookingEligibilityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=[{"code": item.code, "message": item.message} for item in error.failures],
    )


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: CreateBookingRequest, current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    """Book a place on a timetable session (see GET /sessions for the session ids)."""
    try:
        return await service.create(current_user.id, payload.timetable_session_id)
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
) -> Any:
    """The member's session waiting lists, including any place currently offered to them."""
    return await service.list_waitlist_for_user(current_user.id)


@router.post(
    "/waitlist/{entry_id}/accept",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_waitlist_offer(
    entry_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    """Take up an offered place. Eligibility is checked again; a refusal ends the offer."""
    try:
        return await service.accept_offer(current_user.id, entry_id)
    except WaitlistEntryNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingEligibilityError as error:
        raise eligibility_error(error) from error


@router.get("/me", response_model=list[BookingResponse])
async def list_my_bookings(
    current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    return await service.list_for_user(current_user.id)


@router.post(
    "/{booking_id}/waitlist", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED
)
async def join_waitlist(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    try:
        entry = await service.join_waitlist(current_user.id, booking_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return entry


@router.post("/{booking_id}/check-in", response_model=BookingResponse)
async def check_in_to_booking(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    try:
        return await service.check_in(current_user.id, booking_id)
    except BookingNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete("/{booking_id}", response_model=BookingResponse)
async def cancel_booking(
    booking_id: int, current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    try:
        return await service.cancel(current_user.id, booking_id)
    except BookingNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
