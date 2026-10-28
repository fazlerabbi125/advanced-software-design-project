from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.dependencies import DbSessionDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.bookings.dependencies import BookingServiceDependency
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.schemas import (
    BookingResponse,
    CreateBookingRequest,
    SessionWaitlistResponse,
)
from app.modules.bookings.service import (
    BookingNotFoundError,
    BookingStateError,
    SessionFullError,
    SessionNotFoundError,
    WaitlistEntryNotFoundError,
)
from app.modules.notifications.dependencies import (
    NotificationObserverDependency,
    NotificationPublisherDependency,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


def eligibility_error(error: BookingEligibilityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"code": item.code, "message": item.message} for item in error.failures],
    )


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    description="Book a timetable session.",
)
async def create_booking(
    payload: CreateBookingRequest,
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDependency,
    notifications: NotificationObserverDependency,
    publisher: NotificationPublisherDependency,
) -> Any:
    try:
        booking = await service.create(current_user.id, payload.timetable_session_id)
    except SessionNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SessionFullError as error:
        await session.commit()
        await publisher.publish_many(notifications.drain())
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingStateError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingEligibilityError as error:
        await session.rollback()
        raise eligibility_error(error) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await publisher.publish_many(notifications.drain())
    return booking


@router.get(
    "/waitlist/me",
    response_model=list[SessionWaitlistResponse],
    description="List your waitlist entries.",
)
async def list_my_waitlist_entries(
    current_user: CurrentUser, service: BookingServiceDependency
) -> Any:
    return await service.list_waitlist_for_user(current_user.id)


@router.post(
    "/waitlist/{entry_id}/accept",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    description="Accept an offered waitlist place.",
)
async def accept_waitlist_offer(
    entry_id: int,
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDependency,
    notifications: NotificationObserverDependency,
    publisher: NotificationPublisherDependency,
) -> Any:
    try:
        booking = await service.accept_offer(current_user.id, entry_id)
    except WaitlistEntryNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except BookingEligibilityError as error:
        if getattr(error, "commit_required", False):
            await session.commit()
            await publisher.publish_many(notifications.drain())
        else:
            await session.rollback()
        raise eligibility_error(error) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await publisher.publish_many(notifications.drain())
    return booking


@router.get("/me", response_model=list[BookingResponse], description="List your bookings.")
async def list_my_bookings(current_user: CurrentUser, service: BookingServiceDependency) -> Any:
    return await service.list_for_user(current_user.id)


@router.post(
    "/{booking_id}/check-in", response_model=BookingResponse, description="Check in to a booking."
)
async def check_in_to_booking(
    booking_id: int,
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDependency,
) -> Any:
    try:
        booking = await service.check_in(current_user.id, booking_id)
    except BookingNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return booking


@router.delete(
    "/{booking_id}", response_model=BookingResponse, description="Cancel one of your bookings."
)
async def cancel_booking(
    booking_id: int,
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDependency,
    notifications: NotificationObserverDependency,
    publisher: NotificationPublisherDependency,
) -> Any:
    try:
        booking = await service.cancel(current_user.id, booking_id)
    except BookingNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except BookingStateError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await publisher.publish_many(notifications.drain())
    return booking
