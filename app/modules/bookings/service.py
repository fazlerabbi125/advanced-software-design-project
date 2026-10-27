from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import User
from app.models.bookings import (
    Booking,
    BookingResourceType,
    BookingStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.models.sessions import TimetableSession
from app.modules.bookings.builder import BookingContextBuilder
from app.modules.bookings.eligibility import (
    BookingContext,
    BookingEligibilityError,
    build_eligibility_chain,
)
from app.modules.memberships.service import MembershipService
from app.utils.constants import (
    CHECK_IN_GRACE_MINUTES,
    POOL_OFFER_CUTOFF_MINUTES,
    WAITLIST_OFFER_MINUTES,
)
from app.utils.helpers import utc_now


class SessionNotFoundError(LookupError):
    pass


class BookingNotFoundError(LookupError):
    pass


class BookingStateError(ValueError):
    pass


class WaitlistEntryNotFoundError(LookupError):
    pass


class SessionFullError(Exception):
    """The session has no free places; the member was put on its waiting list."""

    def __init__(self, position: int) -> None:
        self.position = position
        super().__init__(f"this session is full, you are number {position} on the waiting list")


def offer_deadline(offered_at: datetime, timetable_session: TimetableSession) -> datetime:
    """When a waitlist offer made at offered_at stops being open."""
    if timetable_session.resource_type == BookingResourceType.POOL:
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
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.memberships = MembershipService(session)

    async def create(self, user_id: int, session_id: int) -> Booking:
        timetable_session = await self._lock_session(session_id)
        await self._lock_member(user_id)
        context = await self._build_context(user_id, timetable_session)
        await self._ensure_eligible(context)
        # Only eligible members reach the waiting list.
        if timetable_session.is_full:
            raise SessionFullError(await self._join_session_waitlist(user_id, session_id))
        booking = await self._booking_row(user_id, timetable_session, context.bookings)
        self._confirm(booking, timetable_session)
        await self.session.commit()
        await self.session.refresh(booking)
        return booking

    async def _lock_session(self, session_id: int) -> TimetableSession:
        """Lock the timetable session so two members cannot take the last place together."""
        timetable_session = await self.session.scalar(
            select(TimetableSession).where(TimetableSession.id == session_id).with_for_update()
        )
        if timetable_session is None:
            await self.session.rollback()
            raise SessionNotFoundError("session was not found")
        return timetable_session

    async def _lock_member(self, user_id: int) -> None:
        """Serialize this member's eligibility check and write, including membership changes."""
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def _build_context(
        self, user_id: int, timetable_session: TimetableSession
    ) -> BookingContext:
        builder = BookingContextBuilder(self.session, user_id, utc_now())
        builder.with_session(timetable_session)
        await builder.with_membership(self.memberships)
        await builder.with_weekly_bookings()
        await builder.with_no_show_penalties()
        return builder.build()

    async def _ensure_eligible(self, context: BookingContext) -> None:
        failures = build_eligibility_chain().handle(context)
        if failures:
            await self.session.rollback()
            raise BookingEligibilityError(failures)

    async def _booking_row(
        self, user_id: int, timetable_session: TimetableSession, bookings: Sequence[Booking]
    ) -> Booking:
        """Return the member's cancelled row for this slot to reuse, or a new row.

        The bookings unique constraint includes cancelled rows, so rebooking a cancelled
        session must reuse that row instead of inserting a duplicate.
        """
        existing = _same_slot(bookings, timetable_session)
        if existing is None:
            booking = Booking(user_id=user_id)
            self.session.add(booking)
            return booking
        if existing.status != BookingStatus.CANCELLED:
            await self.session.rollback()
            raise BookingStateError("you already have a booking for this session")
        return existing

    @staticmethod
    def _confirm(booking: Booking, timetable_session: TimetableSession) -> None:
        """Copy the session details onto the booking and take one place."""
        booking.session_id = timetable_session.id
        booking.resource_name = timetable_session.resource_name
        booking.resource_type = timetable_session.resource_type
        booking.starts_at = timetable_session.starts_at
        booking.ends_at = timetable_session.ends_at
        booking.status = BookingStatus.CONFIRMED
        timetable_session.allocated_count += 1

    async def release_places(
        self, timetable_session: TimetableSession, count: int, now: datetime
    ) -> None:
        """Give back places on a locked session and offer each to the next waiting member.

        The caller commits. An offered place stays allocated, so it is held for that
        member until they accept it or the offer expires.
        """
        timetable_session.allocated_count = max(timetable_session.allocated_count - count, 0)
        for _ in range(count):
            if await self._offer_next_place(timetable_session, now) is None:
                break

    async def _offer_next_place(
        self, timetable_session: TimetableSession, now: datetime
    ) -> WaitlistEntry | None:
        if timetable_session.is_full:
            return None
        if offer_deadline(now, timetable_session) <= now:
            return None  # Too late for anyone to take up an offer.
        entry = await self.session.scalar(
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
        return entry

    async def accept_offer(self, user_id: int, entry_id: int) -> Booking:
        """Turn the member's open waitlist offer into a confirmed booking.

        Eligibility is checked again. If the member no longer qualifies, the offer ends,
        the place goes to the next waiting member and the reasons are raised.
        """
        session_id = await self.session.scalar(
            select(WaitlistEntry.session_id).where(
                WaitlistEntry.id == entry_id, WaitlistEntry.user_id == user_id
            )
        )
        if session_id is None:
            raise WaitlistEntryNotFoundError("waitlist entry was not found")
        # Lock the session before the entry, in the same order as the other writers.
        timetable_session = await self._lock_session(session_id)
        entry = await self.session.scalar(
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
            await self.session.rollback()
            raise BookingStateError("there is no open offer on this waitlist entry")
        await self._lock_member(user_id)
        context = await self._build_context(user_id, timetable_session)
        failures = build_eligibility_chain().handle(context)
        if failures:
            entry.status = WaitlistStatus.EXPIRED
            await self.release_places(timetable_session, 1, now)
            await self.session.commit()
            raise BookingEligibilityError(failures)

        booking = await self._booking_row(user_id, timetable_session, context.bookings)
        # The place was held for this member when the offer was made; hand it over
        # rather than take a second one.
        timetable_session.allocated_count -= 1
        self._confirm(booking, timetable_session)
        entry.status = WaitlistStatus.ACCEPTED
        await self.session.commit()
        await self.session.refresh(booking)
        return booking

    async def list_waitlist_for_user(self, user_id: int) -> list[WaitlistEntry]:
        statement = (
            select(WaitlistEntry)
            .where(WaitlistEntry.user_id == user_id, WaitlistEntry.session_id.is_not(None))
            .options(selectinload(WaitlistEntry.session))
            .order_by(WaitlistEntry.id.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def _join_session_waitlist(self, user_id: int, session_id: int) -> int:
        """Add the member to the session's waiting list (once) and return their position."""
        entry = await self.session.scalar(
            select(WaitlistEntry).where(
                WaitlistEntry.session_id == session_id, WaitlistEntry.user_id == user_id
            )
        )
        if entry is not None and entry.status in (WaitlistStatus.EXPIRED, WaitlistStatus.ACCEPTED):
            # A member whose offer lapsed (or whose accepted place was later given up) joins
            # again at the back of the list, with a new entry.
            await self.session.delete(entry)
            await self.session.flush()
            entry = None
        if entry is None:
            entry = WaitlistEntry(
                session_id=session_id, user_id=user_id, status=WaitlistStatus.WAITING
            )
            self.session.add(entry)
            await self.session.flush()
        position = await self.session.scalar(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.session_id == session_id,
                WaitlistEntry.status == WaitlistStatus.WAITING,
                WaitlistEntry.id <= entry.id,
            )
        )
        await self.session.commit()
        return position or 0

    async def join_waitlist(self, user_id: int, booking_id: int) -> WaitlistEntry:
        booking = await self.session.get(Booking, booking_id)
        if booking is None or booking.status != BookingStatus.CONFIRMED:
            raise ValueError("booking is not available for a waitlist")
        existing = await self.session.scalar(
            select(WaitlistEntry).where(
                WaitlistEntry.booking_id == booking_id,
                WaitlistEntry.user_id == user_id,
            )
        )
        if existing is not None:
            raise ValueError("already on this waitlist")
        waitlist_entry = WaitlistEntry(
            booking_id=booking_id,
            user_id=user_id,
            status=WaitlistStatus.WAITING,
        )
        self.session.add(waitlist_entry)
        await self.session.commit()
        await self.session.refresh(waitlist_entry)
        return waitlist_entry

    async def list_for_user(self, user_id: int) -> list[Booking]:
        statement = (
            select(Booking).where(Booking.user_id == user_id).order_by(Booking.starts_at.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def _locked_owned_booking(self, user_id: int, booking_id: int) -> Booking:
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.user_id == user_id)
            .with_for_update()
        )
        if booking is None:
            raise BookingNotFoundError("booking was not found")
        return booking

    async def cancel(self, user_id: int, booking_id: int) -> Booking:
        booking = await self._locked_owned_booking(user_id, booking_id)
        if booking.status != BookingStatus.CONFIRMED:
            message = f"a {booking.status.value} booking cannot be cancelled"
            await self.session.rollback()
            raise BookingStateError(message)
        if booking.session_id is not None:
            # Give the place back to the session.
            timetable_session = await self.session.scalar(
                select(TimetableSession)
                .where(TimetableSession.id == booking.session_id)
                .with_for_update()
            )
            if timetable_session is not None:
                await self.release_places(timetable_session, 1, utc_now())
        booking.status = BookingStatus.CANCELLED
        await self.session.commit()
        await self.session.refresh(booking)
        return booking

    async def check_in(self, user_id: int, booking_id: int) -> Booking:
        booking = await self._locked_owned_booking(user_id, booking_id)
        if booking.status != BookingStatus.CONFIRMED:
            await self.session.rollback()
            raise BookingStateError("only a confirmed booking can be checked in")
        booking.status = BookingStatus.CHECKED_IN
        await self.session.commit()
        await self.session.refresh(booking)
        return booking
