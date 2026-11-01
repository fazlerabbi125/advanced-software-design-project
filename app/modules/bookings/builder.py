"""Builder that assembles a BookingContext step by step.

Pattern: Builder (creational). The eligibility rules (Chain of Responsibility) need a
context made from several separate queries: the timetable session, the member's
membership, their bookings that week, their recent no-shows and, for equipment, their
slots of that type on the day. The builder keeps
that loading out of BookingService.create, lets each step be tested on its own, and
refuses to build a context that is missing a required part.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Self
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking, BookingStatus
from app.models.facilities import EquipmentUnit
from app.models.timetable_sessions import TimetableSession
from app.modules.bookings.eligibility import BookingContext, week_bounds
from app.shared.constants import NO_SHOW_PENALTY_DAYS, NO_SHOW_PENALTY_LIMIT

if TYPE_CHECKING:
    from app.models.memberships import Membership
    from app.modules.memberships.service import MembershipService


class BookingContextBuilder:
    """Fluent builder for the immutable BookingContext used by the eligibility chain."""

    def __init__(self, db: AsyncSession, user_id: UUID, now: datetime) -> None:
        self.db = db
        self.user_id = user_id
        self.now = now
        self.timetable_session: TimetableSession | None = None
        self.membership: Membership | None = None
        self.membership_loaded = False
        self.bookings: list[Booking] = []
        self.has_unresolved_no_shows = False
        self.equipment_slots_that_day = 0

    def with_session(self, timetable_session: TimetableSession) -> Self:
        """Use the (already locked) timetable session being booked."""
        self.timetable_session = timetable_session
        return self

    async def with_membership(self, memberships: MembershipService) -> Self:
        """Load the member's current membership with its plan and entitlements."""
        self.membership = await memberships.booking_membership(
            self.db, self.user_id, self.now.date()
        )
        self.membership_loaded = True
        return self

    async def with_weekly_bookings(self) -> Self:
        """Load the member's bookings in the same Monday-Sunday week as the session."""
        if self.timetable_session is None:
            raise ValueError("set the session before loading weekly bookings")
        week_start, week_end = week_bounds(self.timetable_session.starts_at)
        statement = select(Booking).where(
            Booking.user_id == self.user_id,
            Booking.starts_at >= week_start,
            Booking.starts_at < week_end,
        )
        self.bookings = list((await self.db.scalars(statement)).all())
        return self

    async def with_no_show_penalties(self) -> Self:
        """Flag the member if they missed too many booked sessions recently."""
        since = self.now - timedelta(days=NO_SHOW_PENALTY_DAYS)
        no_shows = await self.db.scalar(
            select(func.count(Booking.id)).where(
                Booking.user_id == self.user_id,
                Booking.status == BookingStatus.NO_SHOW,
                Booking.starts_at >= since,
            )
        )
        self.has_unresolved_no_shows = (no_shows or 0) >= NO_SHOW_PENALTY_LIMIT
        return self

    async def with_equipment_usage(self) -> Self:
        """For an equipment slot, count the member's slots of that type on the same day."""
        if self.timetable_session is None:
            raise ValueError("set the session before loading equipment usage")
        if self.timetable_session.equipment_unit_id is None:
            return self
        unit_type = await self.db.scalar(
            select(EquipmentUnit.equipment_type).where(
                EquipmentUnit.id == self.timetable_session.equipment_unit_id
            )
        )
        day_start = self.timetable_session.starts_at.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.equipment_slots_that_day = (
            await self.db.scalar(
                select(func.count(Booking.id))
                .join(TimetableSession, Booking.timetable_session_id == TimetableSession.id)
                .join(EquipmentUnit, TimetableSession.equipment_unit_id == EquipmentUnit.id)
                .where(
                    Booking.user_id == self.user_id,
                    Booking.status != BookingStatus.CANCELLED,
                    EquipmentUnit.equipment_type == unit_type,
                    Booking.starts_at >= day_start,
                    Booking.starts_at < day_start + timedelta(days=1),
                )
            )
            or 0
        )
        return self

    def build(self) -> BookingContext:
        """Return the finished context; fail if a required step was skipped."""
        if self.timetable_session is None:
            raise ValueError("cannot build a booking context without a session")
        if not self.membership_loaded:
            raise ValueError("cannot build a booking context without loading the membership")
        return BookingContext(
            now=self.now,
            starts_at=self.timetable_session.starts_at,
            resource_type=self.timetable_session.resource_type,
            membership=self.membership,
            bookings=self.bookings,
            has_unresolved_no_shows=self.has_unresolved_no_shows,
            equipment_slots_that_day=self.equipment_slots_that_day,
        )
