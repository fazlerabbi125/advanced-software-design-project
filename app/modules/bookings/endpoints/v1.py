from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.dependencies import DbSessionDep
from app.core.exceptions import AppError, http_error
from app.modules.auth.dependencies import CurrentUser
from app.modules.bookings.dependencies import BookingServiceDep
from app.modules.bookings.schemas import (
    BookingResponse,
    CreateBookingRequest,
    SessionWaitlistResponse,
)
from app.modules.notifications.dependencies import (
    NotificationObserverDep,
    NotificationPublisherDep,
)
from app.shared.pagination import CursorParamsDep, CursorResponse

router = APIRouter(prefix="/bookings", tags=["bookings"])


def eligibility_error(error: AppError) -> HTTPException:
    details = error.errors
    if isinstance(details, dict):
        details = details.get("failures", [])
    if details:
        details = [{"code": item.code, "message": item.message} for item in details]
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(details or []),
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
    service: BookingServiceDep,
    notifications: NotificationObserverDep,
    publisher: NotificationPublisherDep,
) -> Any:
    pending_notifications: list = []
    try:
        booking = await service.create(
            session, pending_notifications, current_user.id, payload.timetable_session_id
        )
    except AppError as error:
        if isinstance(error.errors, dict) and error.errors.get("commit_required"):
            await session.commit()
            await publisher.publish_many(pending_notifications)
        else:
            await session.rollback()
        if error.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            raise eligibility_error(error) from error
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await publisher.publish_many(pending_notifications)
    return booking


@router.get(
    "/waitlist/me",
    response_model=CursorResponse[SessionWaitlistResponse],
    description="List your waitlist entries.",
)
async def list_my_waitlist_entries(
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDep,
    params: CursorParamsDep,
) -> Any:
    result = await service.list_waitlist_for_user(session, current_user.id, params)
    return {"items": result.items, "meta": result.meta}


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
    service: BookingServiceDep,
    notifications: NotificationObserverDep,
    publisher: NotificationPublisherDep,
) -> Any:
    pending_notifications: list = []
    try:
        booking = await service.accept_offer(
            session, pending_notifications, current_user.id, entry_id
        )
    except AppError as error:
        if isinstance(error.errors, dict) and error.errors.get("commit_required"):
            await session.commit()
            await publisher.publish_many(pending_notifications)
        else:
            await session.rollback()
        if error.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            raise eligibility_error(error) from error
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await publisher.publish_many(pending_notifications)
    return booking


@router.get(
    "/me", response_model=CursorResponse[BookingResponse], description="List your bookings."
)
async def list_my_bookings(
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDep,
    params: CursorParamsDep,
) -> Any:
    result = await service.list_for_user(session, current_user.id, params)
    return {"items": result.items, "meta": result.meta}


@router.post(
    "/{booking_id}/check-in", response_model=BookingResponse, description="Check in to a booking."
)
async def check_in_to_booking(
    booking_id: int,
    current_user: CurrentUser,
    session: DbSessionDep,
    service: BookingServiceDep,
) -> Any:
    try:
        booking = await service.check_in(session, current_user.id, booking_id)
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
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
    service: BookingServiceDep,
    notifications: NotificationObserverDep,
    publisher: NotificationPublisherDep,
) -> Any:
    pending_notifications: list = []
    try:
        booking = await service.cancel(session, pending_notifications, current_user.id, booking_id)
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await publisher.publish_many(pending_notifications)
    return booking
