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

from app.models import Base, Booking, BookingResourceType, BookingStatus, User
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.service import BookingService
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
        self.clock = patch("app.modules.bookings.service.utc_now", return_value=NOW)
        self.clock.start()

    async def asyncTearDown(self):
        self.clock.stop()
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def create(self, minutes=0):
        async with self.sessions() as session:
            return await BookingService(session).create(
                self.user_id,
                "Class",
                BookingResourceType.CLASS,
                NOW + timedelta(days=1, minutes=minutes),
            )

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

    async def test_naive_time_rejected(self):
        async with self.sessions() as session:
            with self.assertRaisesRegex(ValueError, "timezone"):
                await BookingService(session).create(
                    self.user_id, "Class", BookingResourceType.CLASS, NOW.replace(tzinfo=None)
                )

    async def test_missing_membership_rejected(self):
        async with self.sessions() as session:
            user = User(email="other@example.test", password_hash="unused")
            session.add(user)
            await session.commit()
            with self.assertRaises(BookingEligibilityError) as raised:
                await BookingService(session).create(
                    user.id, "Class", BookingResourceType.CLASS, NOW + timedelta(days=1)
                )
            self.assertEqual(
                [item.code for item in raised.exception.failures], ["membership_inactive"]
            )
