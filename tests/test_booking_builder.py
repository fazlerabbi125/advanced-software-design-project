import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.models.bookings import BookingResourceType
from app.models.timetable_sessions import TimetableSession
from app.modules.bookings.builder import BookingContextBuilder
from app.modules.bookings.eligibility import build_eligibility_chain
from app.shared.constants import NO_SHOW_PENALTY_LIMIT
from tests.test_booking_eligibility import NOW, booking, membership


def timetable_session(days=1, resource_type=BookingResourceType.CLASS):
    starts_at = NOW + timedelta(days=days)
    return TimetableSession(
        id=7,
        resource_name="Spin",
        resource_type=resource_type,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=45),
        capacity=10,
        allocated_count=0,
    )


def fake_db(bookings=(), no_shows=0):
    """A stand-in database session; the builder only calls scalars() and scalar()."""
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = list(bookings)
    db.scalars = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=no_shows)
    return db


def fake_memberships(member):
    service = MagicMock()
    service.booking_membership = AsyncMock(return_value=member)
    return service


class BookingContextBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, db, member, slot):
        builder = BookingContextBuilder(db, user_id=uuid4(), now=NOW).with_session(slot)
        await builder.with_membership(fake_memberships(member))
        await builder.with_weekly_bookings()
        await builder.with_no_show_penalties()
        return builder.build()

    async def test_builds_context_from_each_step(self):
        slot = timetable_session(resource_type=BookingResourceType.POOL)
        member = membership()
        earlier = booking(NOW + timedelta(hours=2))
        context = await self.build(fake_db(bookings=[earlier]), member, slot)
        self.assertEqual(context.now, NOW)
        self.assertEqual(context.starts_at, slot.starts_at)
        self.assertEqual(context.resource_type, BookingResourceType.POOL)
        self.assertIs(context.membership, member)
        self.assertEqual(list(context.bookings), [earlier])
        self.assertFalse(context.has_unresolved_no_shows)

    async def test_no_show_limit_sets_the_penalty_flag(self):
        for no_shows, expected in (
            (NO_SHOW_PENALTY_LIMIT - 1, False),
            (NO_SHOW_PENALTY_LIMIT, True),
        ):
            with self.subTest(no_shows=no_shows):
                context = await self.build(
                    fake_db(no_shows=no_shows), membership(), timetable_session()
                )
                self.assertEqual(context.has_unresolved_no_shows, expected)

    async def test_penalty_is_reported_by_the_chain(self):
        context = await self.build(
            fake_db(no_shows=NO_SHOW_PENALTY_LIMIT), membership(), timetable_session()
        )
        codes = [failure.code for failure in build_eligibility_chain().handle(context)]
        self.assertEqual(codes, ["no_show_penalty"])

    async def test_refuses_to_build_without_required_steps(self):
        with self.assertRaisesRegex(ValueError, "without a session"):
            BookingContextBuilder(fake_db(), uuid4(), NOW).build()
        with self.assertRaisesRegex(ValueError, "set the session"):
            await BookingContextBuilder(fake_db(), uuid4(), NOW).with_weekly_bookings()
        with self.assertRaisesRegex(ValueError, "membership"):
            BookingContextBuilder(fake_db(), uuid4(), NOW).with_session(timetable_session()).build()


if __name__ == "__main__":
    unittest.main()
