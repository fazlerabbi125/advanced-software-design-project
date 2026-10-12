from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.memberships.service import MembershipService
from app.models.bookings import (
    Booking,
    BookingResourceType,
    BookingStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.models.memberships import MembershipEntitlement
from app.utils.constants import BOOKING_WINDOW_DAYS
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
        now = utc_now()
        if starts_at <= now:
            raise ValueError("booking must be in the future")
        if starts_at > now + timedelta(days=BOOKING_WINDOW_DAYS):
            raise ValueError("booking is outside the allowed booking window")
        required_entitlement = {
            BookingResourceType.CLASS: MembershipEntitlement.CLASS_BOOKING,
            BookingResourceType.POOL: MembershipEntitlement.POOL_BOOKING,
            BookingResourceType.PERSONAL_TRAINING: MembershipEntitlement.PERSONAL_TRAINING,
        }[resource_type]
        if not await self.memberships.has_entitlement(
            user_id, required_entitlement, starts_at.date()
        ):
            raise ValueError("your membership plan does not allow this booking type")
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
