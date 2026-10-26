"""Use an explicitly supplied disposable PostgreSQL database, never the app database.

BFS_TEST_DATABASE_URL=postgresql+asyncpg://... uv run python -m unittest discover -s tests -v
The tests create and drop their own schema within that database.
"""

import asyncio
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Base,
    Booking,
    BookingResourceType,
    BookingStatus,
    TimetableSession,
    User,
    WaitlistEntry,
)
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.service import (
    BookingService,
    BookingStateError,
    SessionFullError,
    SessionNotFoundError,
)
from tests.test_booking_eligibility import NOW, membership


@unittest.skipUnless(os.getenv("BFS_TEST_DATABASE_URL"), "set a disposable BFS_TEST_DATABASE_URL")
class BookingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "booking_test_" + uuid4().hex
        url = os.environ["BFS_TEST_DATABASE_URL"]
        self.admin = create_async_engine(url)
        async with self.admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": self.schema}}
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as session:
            user = User(email="member@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            self.user_id = user.id
            member = membership(limit=1)
            member.user_id = user.id
            member.plan.price_minor = 4500
            session.add(member)
            await session.commit()
        self.session_ids = {}
        self.clock = patch("app.modules.bookings.service.utc_now", return_value=NOW)
        self.clock.start()

    async def asyncTearDown(self):
        self.clock.stop()
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def add_session(self, minutes=0, capacity=10):
        async with self.sessions() as session:
            starts_at = NOW + timedelta(days=1, minutes=minutes)
            timetable_session = TimetableSession(
                resource_name="Class",
                resource_type=BookingResourceType.CLASS,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=45),
                capacity=capacity,
                allocated_count=0,
            )
            session.add(timetable_session)
            await session.commit()
            return timetable_session.id

    async def book(self, session_id, user_id=None):
        async with self.sessions() as session:
            return await BookingService(session).create(user_id or self.user_id, session_id)

    async def create(self, minutes=0):
        session_id = self.session_ids.get(minutes)
        if session_id is None:
            session_id = self.session_ids[minutes] = await self.add_session(minutes)
        return await self.book(session_id)

    async def add_member(self, email):
        async with self.sessions() as session:
            user = User(email=email, password_hash="unused")
            session.add(user)
            await session.flush()
            member = membership()
            member.user_id = user.id
            member.plan.name = email
            member.plan.price_minor = 4500
            session.add(member)
            await session.commit()
            return user.id

    async def allocated(self, session_id):
        async with self.sessions() as session:
            return (await session.get(TimetableSession, session_id)).allocated_count

    async def test_success_then_rejection_does_not_write(self):
        result = await self.create()
        self.assertEqual(result.status, BookingStatus.CONFIRMED)
        with self.assertRaises(BookingEligibilityError) as raised:
            await self.create()
        self.assertEqual(
            [item.code for item in raised.exception.failures], ["weekly_limit", "time_conflict"]
        )
        async with self.sessions() as session:
            self.assertEqual(len((await session.scalars(select(Booking))).all()), 1)

    async def test_concurrent_requests_cannot_exceed_weekly_limit(self):
        results = await asyncio.gather(self.create(), self.create(60), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, Booking) for item in results), 1)
        failures = [item for item in results if isinstance(item, BookingEligibilityError)]
        self.assertEqual(len(failures), 1)
        self.assertEqual([item.code for item in failures[0].failures], ["weekly_limit"])

    async def test_cancelled_slot_can_be_rebooked(self):
        first = await self.create()
        async with self.sessions() as session:
            await BookingService(session).cancel(self.user_id, first.id)
        second = await self.create()
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.status, BookingStatus.CONFIRMED)

    async def test_unknown_session_rejected(self):
        with self.assertRaises(SessionNotFoundError):
            await self.book(999_999)

    async def test_missing_membership_rejected(self):
        async with self.sessions() as session:
            user = User(email="other@example.test", password_hash="unused")
            session.add(user)
            await session.commit()
            session_id = await self.add_session()
            with self.assertRaises(BookingEligibilityError) as raised:
                await BookingService(session).create(user.id, session_id)
            self.assertEqual(
                [item.code for item in raised.exception.failures], ["membership_inactive"]
            )

    async def test_booking_takes_a_place_and_cancelling_gives_it_back(self):
        session_id = await self.add_session()
        booking = await self.book(session_id)
        self.assertEqual(booking.session_id, session_id)
        self.assertEqual(await self.allocated(session_id), 1)
        async with self.sessions() as session:
            await BookingService(session).cancel(self.user_id, booking.id)
        self.assertEqual(await self.allocated(session_id), 0)

    async def test_full_session_puts_member_on_waiting_list(self):
        session_id = await self.add_session(capacity=1)
        await self.book(session_id)
        other = await self.add_member("other@example.test")
        with self.assertRaises(SessionFullError) as raised:
            await self.book(session_id, other)
        self.assertEqual(raised.exception.position, 1)
        # Trying again does not add a second waiting-list entry.
        with self.assertRaises(SessionFullError):
            await self.book(session_id, other)
        async with self.sessions() as session:
            entries = (await session.scalars(select(WaitlistEntry))).all()
            self.assertEqual(
                [(item.session_id, item.user_id) for item in entries], [(session_id, other)]
            )
        self.assertEqual(await self.allocated(session_id), 1)

    async def test_last_place_cannot_be_taken_twice(self):
        session_id = await self.add_session(capacity=1)
        first = await self.add_member("first@example.test")
        second = await self.add_member("second@example.test")
        results = await asyncio.gather(
            self.book(session_id, first), self.book(session_id, second), return_exceptions=True
        )
        self.assertEqual(sum(isinstance(item, Booking) for item in results), 1)
        self.assertEqual(sum(isinstance(item, SessionFullError) for item in results), 1)
        self.assertEqual(await self.allocated(session_id), 1)

    async def test_check_in_only_once(self):
        booking = await self.create()
        async with self.sessions() as session:
            checked_in = await BookingService(session).check_in(self.user_id, booking.id)
        self.assertEqual(checked_in.status, BookingStatus.CHECKED_IN)
        async with self.sessions() as session:
            with self.assertRaises(BookingStateError):
                await BookingService(session).check_in(self.user_id, booking.id)
            with self.assertRaises(BookingStateError):
                await BookingService(session).cancel(self.user_id, booking.id)
