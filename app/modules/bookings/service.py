from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.bookings import (
    Booking,
    BookingResourceType,
    BookingStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.modules.bookings.eligibility import (
    BookingContext,
    BookingEligibilityError,
    build_eligibility_chain,
    week_bounds,
)
from app.modules.memberships.service import MembershipService
from app.utils.helpers import utc_now


class BookingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.memberships = MembershipService(session)

    async def create(
        self,
        user_id: int,
        resource_name: str,
        resource_type: BookingResourceType,
        starts_at: datetime,
    ) -> Booking:
        if starts_at.tzinfo is None or starts_at.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        starts_at = starts_at.astimezone(UTC)
        # Serialize this member's eligibility check and write, including membership changes.
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())
        now = utc_now()
        membership = await self.memberships.booking_membership(user_id, now.date())
        week_start, week_end = week_bounds(starts_at)
        bookings = list(
            (
                await self.session.scalars(
                    select(Booking).where(
                        Booking.user_id == user_id,
                        Booking.starts_at >= week_start,
                        Booking.starts_at < week_end,
                    )
                )
            ).all()
        )
        failures = build_eligibility_chain().handle(
            BookingContext(now, starts_at, resource_type, membership, bookings)
        )
        if failures:
            await self.session.rollback()
            raise BookingEligibilityError(failures)
        # The existing unique constraint includes cancelled bookings. Reuse that row
        # so cancelling and then rebooking the same slot does not raise an IntegrityError.
        booking = next(
            (
                item
                for item in bookings
                if item.resource_name == resource_name.strip() and item.starts_at == starts_at
            ),
            None,
        )
        if booking is not None:
            booking.status = BookingStatus.CONFIRMED
            booking.resource_type = resource_type
            await self.session.commit()
            await self.session.refresh(booking)
            return booking
        booking = Booking(
            user_id=user_id,
            resource_name=resource_name.strip(),
            resource_type=resource_type,
            starts_at=starts_at,
        )
        self.session.add(booking)
        await self.session.commit()
        await self.session.refresh(booking)
        return booking

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

    async def cancel(self, user_id: int, booking_id: int) -> Booking:
        booking = await self.session.scalar(
            select(Booking).where(Booking.id == booking_id, Booking.user_id == user_id)
        )
        if booking is None:
            raise ValueError("booking was not found")
        if booking.status == BookingStatus.CANCELLED:
            raise ValueError("booking is already cancelled")
        booking.status = BookingStatus.CANCELLED
        await self.session.commit()
        await self.session.refresh(booking)
        return booking
