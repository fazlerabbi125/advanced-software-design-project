from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.auth import User
from app.models.bookings import (
    Booking,
    BookingResourceType,
    BookingStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.models.facilities import EquipmentUnit
from app.models.notifications import NotificationType
from app.models.timetable_sessions import TimetableSession
from app.modules.bookings.builder import BookingContextBuilder
from app.modules.bookings.eligibility import (
    BookingContext,
    build_eligibility_chain,
)
from app.modules.memberships.service import MembershipService
from app.modules.notifications.service import NotificationEvent, NotificationObserver
from app.shared.constants import (
    CHECK_IN_GRACE_MINUTES,
    CHECK_IN_OPENS_MINUTES,
    POOL_OFFER_CUTOFF_MINUTES,
    WAITLIST_OFFER_MINUTES,
)
from app.shared.helpers import utc_now


def offer_deadline(offered_at: datetime, timetable_session: TimetableSession) -> datetime:
    """When a waitlist offer made at offered_at stops being open."""
    if timetable_session.resource_type in (BookingResourceType.POOL, BookingResourceType.EQUIPMENT):
        latest = timetable_session.ends_at - timedelta(minutes=POOL_OFFER_CUTOFF_MINUTES)
    else:
        latest = timetable_session.starts_at
    return min(offered_at + timedelta(minutes=WAITLIST_OFFER_MINUTES), latest)


def check_in_deadline(booking: Booking) -> datetime:
    """When a confirmed booking that has not been checked in becomes a no-show."""
    # A booking made after the start still gets the full grace period from when it was made.
    deadline = max(booking.starts_at, booking.created_at) + timedelta(
        minutes=CHECK_IN_GRACE_MINUTES
    )
    return min(deadline, booking.ends_at) if booking.ends_at is not None else deadline


def check_in_opens_at(booking: Booking) -> datetime:
    """The earliest moment the member can check in to a booked session."""
    return booking.starts_at - timedelta(minutes=CHECK_IN_OPENS_MINUTES)


def check_in_problem(booking: Booking, now: datetime) -> str | None:
    """Why the booking cannot be checked in at now, or None if it can.

    Check-in closes at the same deadline the no-show job uses, so a booking is never
    both too late to check in and not yet a no-show.
    """
    if booking.status != BookingStatus.CONFIRMED:
        return "only a confirmed booking can be checked in"
    opens_at = check_in_opens_at(booking)
    if now < opens_at:
        return (
            f"check-in opens at {opens_at:%Y-%m-%d %H:%M} UTC, "
            f"{CHECK_IN_OPENS_MINUTES} minutes before the session starts"
        )
    if now >= check_in_deadline(booking):
        return "check-in has closed for this booking"
    return None


def _same_slot(bookings: Sequence[Booking], timetable_session: TimetableSession) -> Booking | None:
    """The member's booking (in any status) for the same resource and start time, if any."""
    for booking in bookings:
        if (
            booking.resource_name == timetable_session.resource_name
            and booking.starts_at == timetable_session.starts_at
        ):
            return booking
    return None


class BookingService:
    def __init__(
        self,
        memberships: MembershipService,
        notifications: NotificationObserver | None = None,
    ) -> None:
        self.memberships = memberships
        self.notifications = notifications

    async def create(
        self,
        session: AsyncSession,
        pending_notifications: list,
        user_id: UUID,
        timetable_session_id: int,
    ) -> Booking:
        timetable_session = await self._lock_session(session, timetable_session_id)
        await self._ensure_unit_in_service(session, timetable_session)
        await self._lock_member(session, user_id)
        context = await self._build_context(session, user_id, timetable_session)
        await self._ensure_eligible(context)
        # Only eligible members reach the waiting list.
        if timetable_session.is_full:
            position = await self._join_session_waitlist(session, user_id, timetable_session_id)
            raise AppError(
                f"this session is full, you are number {position} on the waiting list",
                409,
                {"commit_required": True, "position": position},
            )
        booking = await self._booking_row(session, user_id, timetable_session, context.bookings)
        self._confirm(booking, timetable_session)
        await self._record_booking(
            session, pending_notifications, booking, NotificationType.BOOKING_CONFIRMED
        )
        return booking

    async def _lock_session(self, session: AsyncSession, session_id: int) -> TimetableSession:
        """Lock the timetable session so two members cannot take the last place together."""
        timetable_session = await session.scalar(
            select(TimetableSession).where(TimetableSession.id == session_id).with_for_update()
        )
        if timetable_session is None:
            raise AppError("session was not found", 404)
        return timetable_session

    async def _ensure_unit_in_service(
        self, session: AsyncSession, timetable_session: TimetableSession
    ) -> None:
        """An equipment slot whose unit is out of service cannot be booked until repaired."""
        if timetable_session.equipment_unit_id is None:
            return
        in_service = await session.scalar(
            select(EquipmentUnit.in_service).where(
                EquipmentUnit.id == timetable_session.equipment_unit_id
            )
        )
        if not in_service:
            raise AppError("this equipment is out of service", 409)

    async def _lock_member(self, session: AsyncSession, user_id: UUID) -> None:
        """Serialize this member's eligibility check and write, including membership changes."""
        await session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def _build_context(
        self, session: AsyncSession, user_id: UUID, timetable_session: TimetableSession
    ) -> BookingContext:
        builder = BookingContextBuilder(session, user_id, utc_now())
        builder.with_session(timetable_session)
        await builder.with_membership(self.memberships)
        await builder.with_weekly_bookings()
        await builder.with_no_show_penalties()
        await builder.with_equipment_usage()
        return builder.build()

    async def _ensure_eligible(self, context: BookingContext) -> None:
        failures = build_eligibility_chain().handle(context)
        if failures:
            raise AppError(
                "booking eligibility failed",
                422,
                failures,
            )

    async def _booking_row(
        self,
        session: AsyncSession,
        user_id: UUID,
        timetable_session: TimetableSession,
        bookings: Sequence[Booking],
    ) -> Booking:
        """Return the member's cancelled row for this slot to reuse, or a new row.

        The bookings unique constraint includes cancelled rows, so rebooking a cancelled
        session must reuse that row instead of inserting a duplicate.
        """
        existing = _same_slot(bookings, timetable_session)
        if existing is None:
            booking = Booking(user_id=user_id)
            session.add(booking)
            return booking
        if existing.status != BookingStatus.CANCELLED:
            raise AppError("you already have a booking for this session", 409)
        return existing

    @staticmethod
    def _confirm(booking: Booking, timetable_session: TimetableSession) -> None:
        """Copy the session details onto the booking and take one place."""
        booking.timetable_session_id = timetable_session.id
        booking.resource_name = timetable_session.resource_name
        booking.resource_type = timetable_session.resource_type
        booking.starts_at = timetable_session.starts_at
        booking.ends_at = timetable_session.ends_at
        booking.status = BookingStatus.CONFIRMED
        timetable_session.allocated_count += 1

    async def release_places(
        self,
        session: AsyncSession,
        pending_notifications: list,
        timetable_session: TimetableSession,
        count: int,
        now: datetime,
    ) -> None:
        """Give back places on a locked session and offer each to the next waiting member.

        The caller commits. An offered place stays allocated, so it is held for that
        member until they accept it or the offer expires.
        """
        timetable_session.allocated_count = max(timetable_session.allocated_count - count, 0)
        for _ in range(count):
            if (
                await self._offer_next_place(session, pending_notifications, timetable_session, now)
                is None
            ):
                break

    async def _offer_next_place(
        self,
        session: AsyncSession,
        pending_notifications: list,
        timetable_session: TimetableSession,
        now: datetime,
    ) -> WaitlistEntry | None:
        if timetable_session.is_full:
            return None
        if offer_deadline(now, timetable_session) <= now:
            return None  # Too late for anyone to take up an offer.
        entry = await session.scalar(
            select(WaitlistEntry)
            .where(
                WaitlistEntry.session_id == timetable_session.id,
                WaitlistEntry.status == WaitlistStatus.WAITING,
            )
            .order_by(WaitlistEntry.id)
            .limit(1)
            .with_for_update()
        )
        if entry is None:
            return None
        entry.status = WaitlistStatus.OFFERED
        entry.offered_at = now
        timetable_session.allocated_count += 1
        await session.flush()
        await self._record(
            session,
            pending_notifications,
            entry.user_id,
            NotificationType.WAITLIST_OFFER_CREATED,
            {
                "waitlist_entry_id": entry.id,
                "timetable_session_id": timetable_session.id,
                "resource_name": timetable_session.resource_name,
                "starts_at": timetable_session.starts_at.isoformat(),
                "offer_expires_at": offer_deadline(now, timetable_session).isoformat(),
            },
        )
        return entry

    async def accept_offer(
        self, session: AsyncSession, pending_notifications: list, user_id: UUID, entry_id: int
    ) -> Booking:
        """Turn the member's open waitlist offer into a confirmed booking.

        Eligibility is checked again. If the member no longer qualifies, the offer ends,
        the place goes to the next waiting member and the reasons are raised.
        """
        session_id = await session.scalar(
            select(WaitlistEntry.session_id).where(
                WaitlistEntry.id == entry_id, WaitlistEntry.user_id == user_id
            )
        )
        if session_id is None:
            raise AppError("waitlist entry was not found", 404)
        # Lock the session before the entry, in the same order as the other writers.
        timetable_session = await self._lock_session(session, session_id)
        entry = await session.scalar(
            select(WaitlistEntry)
            .where(WaitlistEntry.id == entry_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = utc_now()
        if (
            entry.status != WaitlistStatus.OFFERED
            or entry.offered_at is None
            or offer_deadline(entry.offered_at, timetable_session) <= now
        ):
            raise AppError("there is no open offer on this waitlist entry", 409)
        await self._lock_member(session, user_id)
        context = await self._build_context(session, user_id, timetable_session)
        failures = build_eligibility_chain().handle(context)
        if failures:
            entry.status = WaitlistStatus.EXPIRED
            await self.release_places(session, pending_notifications, timetable_session, 1, now)
            raise AppError(
                "booking eligibility failed",
                422,
                {
                    "commit_required": True,
                    "failures": failures,
                },
            )

        booking = await self._booking_row(session, user_id, timetable_session, context.bookings)
        # The place was held for this member when the offer was made; hand it over
        # rather than take a second one.
        timetable_session.allocated_count -= 1
        self._confirm(booking, timetable_session)
        entry.status = WaitlistStatus.ACCEPTED
        await self._record_booking(
            session, pending_notifications, booking, NotificationType.BOOKING_CONFIRMED
        )
        return booking

    async def list_waitlist_for_user(
        self, session: AsyncSession, user_id: UUID
    ) -> list[WaitlistEntry]:
        statement = (
            select(WaitlistEntry)
            .where(WaitlistEntry.user_id == user_id)
            .options(selectinload(WaitlistEntry.session))
            .order_by(WaitlistEntry.id.desc())
        )
        return list((await session.scalars(statement)).all())

    async def _join_session_waitlist(
        self, session: AsyncSession, user_id: UUID, session_id: int
    ) -> int:
        """Add the member to the session's waiting list (once) and return their position."""
        entry = await session.scalar(
            select(WaitlistEntry).where(
                WaitlistEntry.session_id == session_id, WaitlistEntry.user_id == user_id
            )
        )
        if entry is not None and entry.status in (WaitlistStatus.EXPIRED, WaitlistStatus.ACCEPTED):
            # A member whose offer lapsed (or whose accepted place was later given up) joins
            # again at the back of the list, with a new entry.
            await session.delete(entry)
            await session.flush()
            entry = None
        if entry is None:
            entry = WaitlistEntry(
                session_id=session_id, user_id=user_id, status=WaitlistStatus.WAITING
            )
            session.add(entry)
            await session.flush()
        position = await session.scalar(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.session_id == session_id,
                WaitlistEntry.status == WaitlistStatus.WAITING,
                WaitlistEntry.id <= entry.id,
            )
        )
        return position or 0

    async def list_for_user(self, session: AsyncSession, user_id: UUID) -> list[Booking]:
        statement = (
            select(Booking).where(Booking.user_id == user_id).order_by(Booking.starts_at.desc())
        )
        return list((await session.scalars(statement)).all())

    async def _locked_owned_booking(
        self, session: AsyncSession, user_id: UUID, booking_id: int
    ) -> Booking:
        booking = await session.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.user_id == user_id)
            .with_for_update()
        )
        if booking is None:
            raise AppError("booking was not found", 404)
        return booking

    async def cancel(
        self, session: AsyncSession, pending_notifications: list, user_id: UUID, booking_id: int
    ) -> Booking:
        booking = await self._locked_owned_booking(session, user_id, booking_id)
        if booking.status != BookingStatus.CONFIRMED:
            message = f"a {booking.status.value} booking cannot be cancelled"
            raise AppError(message, 409)
        if booking.timetable_session_id is not None:
            # Give the place back to the session.
            timetable_session = await session.scalar(
                select(TimetableSession)
                .where(TimetableSession.id == booking.timetable_session_id)
                .with_for_update()
            )
            if timetable_session is not None:
                await self.release_places(
                    session, pending_notifications, timetable_session, 1, utc_now()
                )
        booking.status = BookingStatus.CANCELLED
        await self._record_booking(
            session, pending_notifications, booking, NotificationType.BOOKING_CANCELLED
        )
        return booking

    async def check_in(self, session: AsyncSession, user_id: UUID, booking_id: int) -> Booking:
        booking = await self._locked_owned_booking(session, user_id, booking_id)
        problem = check_in_problem(booking, utc_now())
        if problem is not None:
            raise AppError(problem, 409)
        booking.status = BookingStatus.CHECKED_IN
        return booking

    async def _record_booking(
        self,
        session: AsyncSession,
        pending_notifications: list,
        booking: Booking,
        event_type: NotificationType,
    ) -> None:
        await self._record(
            session,
            pending_notifications,
            booking.user_id,
            event_type,
            {
                "booking_id": booking.id,
                "timetable_session_id": booking.timetable_session_id,
                "resource_name": booking.resource_name,
                "resource_type": booking.resource_type.value,
                "starts_at": booking.starts_at.isoformat(),
            },
        )

    async def _record(
        self,
        session: AsyncSession,
        pending_notifications: list,
        user_id: UUID,
        event_type: NotificationType,
        payload: dict[str, object],
    ) -> None:
        if self.notifications is not None:
            await self.notifications.observe(
                session,
                pending_notifications,
                NotificationEvent(user_id=user_id, event_type=event_type, payload=payload),
            )
