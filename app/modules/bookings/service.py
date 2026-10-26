from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.bookings import Booking, BookingStatus, WaitlistEntry, WaitlistStatus
from app.models.sessions import TimetableSession
from app.modules.bookings.builder import BookingContextBuilder
from app.modules.bookings.eligibility import BookingEligibilityError, build_eligibility_chain
from app.modules.memberships.service import MembershipService
from app.utils.helpers import utc_now


class SessionNotFoundError(LookupError):
    pass


class BookingNotFoundError(LookupError):
    pass


class BookingStateError(ValueError):
    pass


class SessionFullError(Exception):
    """The session has no free places; the member was put on its waiting list."""

    def __init__(self, position: int) -> None:
        self.position = position
        super().__init__(f"this session is full, you are number {position} on the waiting list")


class BookingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.memberships = MembershipService(session)

    async def create(self, user_id: int, session_id: int) -> Booking:
        # Lock the timetable session so two members cannot take the last place together.
        timetable_session = await self.session.scalar(
            select(TimetableSession).where(TimetableSession.id == session_id).with_for_update()
        )
        if timetable_session is None:
            await self.session.rollback()
            raise SessionNotFoundError("session was not found")
        # Serialize this member's eligibility check and write, including membership changes.
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

        builder = BookingContextBuilder(self.session, user_id, utc_now()).with_session(
            timetable_session
        )
        await builder.with_membership(self.memberships)
        await builder.with_weekly_bookings()
        await builder.with_no_show_penalties()
        context = builder.build()

        failures = build_eligibility_chain().handle(context)
        if failures:
            await self.session.rollback()
            raise BookingEligibilityError(failures)

        # Only eligible members reach the waiting list.
        if timetable_session.allocated_count >= timetable_session.capacity:
            position = await self._join_session_waitlist(user_id, session_id)
            raise SessionFullError(position)

        # The bookings unique constraint includes cancelled rows. Reuse that row so
        # cancelling and then rebooking the same session does not raise an IntegrityError.
        booking = next(
            (
                item
                for item in context.bookings
                if item.resource_name == timetable_session.resource_name
                and item.starts_at == timetable_session.starts_at
            ),
            None,
        )
        if booking is not None and booking.status != BookingStatus.CANCELLED:
            await self.session.rollback()
            raise BookingStateError("you already have a booking for this session")
        if booking is None:
            booking = Booking(user_id=user_id)
            self.session.add(booking)
        booking.session_id = timetable_session.id
        booking.resource_name = timetable_session.resource_name
        booking.resource_type = timetable_session.resource_type
        booking.starts_at = timetable_session.starts_at
        booking.ends_at = timetable_session.ends_at
        booking.status = BookingStatus.CONFIRMED
        timetable_session.allocated_count += 1
        await self.session.commit()
        await self.session.refresh(booking)
        return booking

    async def _join_session_waitlist(self, user_id: int, session_id: int) -> int:
        """Add the member to the session's waiting list (once) and return their position."""
        entry = await self.session.scalar(
            select(WaitlistEntry).where(
                WaitlistEntry.session_id == session_id, WaitlistEntry.user_id == user_id
            )
        )
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
            if timetable_session is not None and timetable_session.allocated_count > 0:
                timetable_session.allocated_count -= 1
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
