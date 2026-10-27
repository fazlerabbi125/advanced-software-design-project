"""Waitlist offers, offer expiry and no-show detection.

The database tests use an explicitly supplied disposable PostgreSQL database:
BFS_TEST_DATABASE_URL=postgresql+asyncpg://... uv run python -m unittest discover -s tests -v
"""

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
    Membership,
    MembershipEntitlement,
    MembershipStatus,
    TimetableSession,
    User,
    WaitlistEntry,
    WaitlistStatus,
)
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.jobs import detect_no_shows, expire_waitlist_offers
from app.modules.bookings.service import (
    BookingService,
    BookingStateError,
    SessionFullError,
    check_in_deadline,
    offer_deadline,
)
from tests.test_booking_eligibility import NOW, membership

CLASS = BookingResourceType.CLASS
POOL = BookingResourceType.POOL
MINUTE = timedelta(minutes=1)


def timetable_session(resource_type=CLASS, starts_at=NOW + timedelta(days=1), minutes=60):
    return TimetableSession(
        resource_name=resource_type.value.title(),
        resource_type=resource_type,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=minutes),
        capacity=1,
        allocated_count=0,
    )


class DeadlineTests(unittest.TestCase):
    def test_offer_lasts_thirty_minutes_but_ends_at_class_start(self):
        session = timetable_session(starts_at=NOW + timedelta(hours=2))
        self.assertEqual(offer_deadline(NOW, session), NOW + 30 * MINUTE)
        self.assertEqual(offer_deadline(NOW + 100 * MINUTE, session), session.starts_at)

    def test_pool_offer_ends_fifteen_minutes_before_the_end(self):
        session = timetable_session(POOL, starts_at=NOW, minutes=60)
        self.assertEqual(offer_deadline(NOW + 10 * MINUTE, session), NOW + 40 * MINUTE)
        self.assertEqual(offer_deadline(NOW + 20 * MINUTE, session), NOW + 45 * MINUTE)

    def test_check_in_deadline(self):
        booking = Booking(starts_at=NOW, ends_at=NOW + 60 * MINUTE, created_at=NOW - MINUTE)
        self.assertEqual(check_in_deadline(booking), NOW + 10 * MINUTE)
        # A booking made after the start gets ten minutes from when it was made...
        booking.created_at = NOW + 5 * MINUTE
        self.assertEqual(check_in_deadline(booking), NOW + 15 * MINUTE)
        # ...but never past the end of the session.
        booking.ends_at = NOW + 12 * MINUTE
        self.assertEqual(check_in_deadline(booking), NOW + 12 * MINUTE)


class SchedulerTests(unittest.TestCase):
    def test_both_jobs_run_every_minute(self):
        from app.core.scheduler import create_scheduler

        jobs = {job.id: job for job in create_scheduler().get_jobs()}
        self.assertEqual(set(jobs), {"run_offer_expiry", "run_no_show_detection"})
        for job in jobs.values():
            self.assertEqual(job.trigger.interval, MINUTE)


@unittest.skipUnless(os.getenv("BFS_TEST_DATABASE_URL"), "set a disposable BFS_TEST_DATABASE_URL")
class BookingJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "booking_jobs_test_" + uuid4().hex
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
        self.clock = patch("app.modules.bookings.service.utc_now", return_value=NOW)
        self.clock.start()

    async def asyncTearDown(self):
        self.clock.stop()
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    def at(self, moment):
        self.clock.stop()
        self.clock = patch("app.modules.bookings.service.utc_now", return_value=moment)
        self.clock.start()

    async def add_member(self, name, entitlements=(MembershipEntitlement.CLASS_BOOKING,)):
        async with self.sessions() as session:
            user = User(email=f"{name}@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            member = membership(entitlements=entitlements)
            member.user_id = user.id
            member.plan.name = name
            member.plan.price_minor = 4500
            session.add(member)
            await session.commit()
            return user.id

    async def add(self, *rows):
        async with self.sessions() as session:
            session.add_all(rows)
            await session.commit()
        return rows[0]

    async def book(self, session_id, user_id):
        async with self.sessions() as session:
            return await BookingService(session).create(user_id, session_id)

    async def join_waitlist(self, session_id, user_id):
        with self.assertRaises(SessionFullError):
            await self.book(session_id, user_id)
        async with self.sessions() as session:
            return await session.scalar(
                select(WaitlistEntry).where(WaitlistEntry.user_id == user_id)
            )

    async def full_class_with_waitlist(self, starts_at=NOW + timedelta(days=1)):
        """A one-place class: Ann has the place, Ben then Cat are waiting."""
        session_id = (await self.add(timetable_session(starts_at=starts_at))).id
        self.ann = await self.add_member("ann")
        self.ben = await self.add_member("ben")
        self.cat = await self.add_member("cat")
        self.ann_booking = await self.book(session_id, self.ann)
        self.ben_entry = await self.join_waitlist(session_id, self.ben)
        self.cat_entry = await self.join_waitlist(session_id, self.cat)
        return session_id

    async def cancel_ann(self):
        async with self.sessions() as session:
            await BookingService(session).cancel(self.ann, self.ann_booking.id)

    async def accept(self, user_id, entry_id):
        async with self.sessions() as session:
            return await BookingService(session).accept_offer(user_id, entry_id)

    async def state(self, session_id):
        """(allocated places, {member: waitlist status})."""
        async with self.sessions() as session:
            allocated = (await session.get(TimetableSession, session_id)).allocated_count
            entries = (await session.scalars(select(WaitlistEntry))).all()
            return allocated, {entry.user_id: entry.status for entry in entries}

    async def run_job(self, job, moment):
        async with self.sessions() as session:
            return await job(session, moment)

    async def test_cancellation_offers_the_place_to_the_first_waiting_member(self):
        session_id = await self.full_class_with_waitlist()
        await self.cancel_ann()
        allocated, statuses = await self.state(session_id)
        # The place stays allocated: it is held for Ben while his offer is open.
        self.assertEqual(allocated, 1)
        self.assertEqual(statuses[self.ben], WaitlistStatus.OFFERED)
        self.assertEqual(statuses[self.cat], WaitlistStatus.WAITING)

    async def test_accepting_an_offer_books_the_held_place(self):
        session_id = await self.full_class_with_waitlist()
        await self.cancel_ann()
        self.at(NOW + 10 * MINUTE)
        booking = await self.accept(self.ben, self.ben_entry.id)
        self.assertEqual((booking.user_id, booking.status), (self.ben, BookingStatus.CONFIRMED))
        allocated, statuses = await self.state(session_id)
        self.assertEqual(allocated, 1)
        self.assertEqual(statuses[self.ben], WaitlistStatus.ACCEPTED)
        # An accepted offer cannot be used twice, and nobody else can take Ben's offer.
        with self.assertRaises(BookingStateError):
            await self.accept(self.ben, self.ben_entry.id)
        with self.assertRaises(LookupError):
            await self.accept(self.cat, self.ben_entry.id)

    async def test_lapsed_offer_passes_to_the_next_member_then_frees_the_place(self):
        session_id = await self.full_class_with_waitlist()
        await self.cancel_ann()
        self.assertEqual(await self.run_job(expire_waitlist_offers, NOW + 29 * MINUTE), 0)
        self.assertEqual(await self.run_job(expire_waitlist_offers, NOW + 30 * MINUTE), 1)
        allocated, statuses = await self.state(session_id)
        self.assertEqual(allocated, 1)
        self.assertEqual(statuses[self.ben], WaitlistStatus.EXPIRED)
        self.assertEqual(statuses[self.cat], WaitlistStatus.OFFERED)
        # Cat's offer lapses too and nobody is left, so the place is free again.
        self.assertEqual(await self.run_job(expire_waitlist_offers, NOW + 60 * MINUTE), 1)
        self.assertEqual((await self.state(session_id))[0], 0)

    async def test_offer_cannot_be_accepted_after_its_deadline(self):
        await self.full_class_with_waitlist()
        await self.cancel_ann()
        self.at(NOW + 30 * MINUTE)
        with self.assertRaises(BookingStateError):
            await self.accept(self.ben, self.ben_entry.id)

    async def test_ineligible_member_loses_the_offer_to_the_next_member(self):
        session_id = await self.full_class_with_waitlist()
        await self.cancel_ann()
        async with self.sessions() as session:
            ben_membership = await session.scalar(
                select(Membership).where(Membership.user_id == self.ben)
            )
            ben_membership.status = MembershipStatus.CANCELLED
            await session.commit()
        with self.assertRaises(BookingEligibilityError) as raised:
            await self.accept(self.ben, self.ben_entry.id)
        self.assertEqual([item.code for item in raised.exception.failures], ["membership_inactive"])
        allocated, statuses = await self.state(session_id)
        self.assertEqual(allocated, 1)
        self.assertEqual(statuses[self.ben], WaitlistStatus.EXPIRED)
        self.assertEqual(statuses[self.cat], WaitlistStatus.OFFERED)

    async def test_member_whose_offer_lapsed_can_join_again_at_the_back(self):
        session_id = await self.full_class_with_waitlist()
        await self.cancel_ann()
        await self.run_job(expire_waitlist_offers, NOW + 30 * MINUTE)
        # Cat now holds the offer; Ben tries again and goes to the back of the list.
        self.at(NOW + 31 * MINUTE)
        with self.assertRaises(SessionFullError) as raised:
            await self.book(session_id, self.ben)
        self.assertEqual(raised.exception.position, 1)
        self.assertEqual((await self.state(session_id))[1][self.ben], WaitlistStatus.WAITING)
        # When Cat's offer lapses too, the place is offered to Ben again.
        await self.run_job(expire_waitlist_offers, NOW + 60 * MINUTE)
        self.assertEqual((await self.state(session_id))[1][self.ben], WaitlistStatus.OFFERED)

    async def test_class_offer_ends_at_the_start_and_is_not_passed_on(self):
        starts_at = NOW + 20 * MINUTE
        session_id = await self.full_class_with_waitlist(starts_at)
        await self.cancel_ann()
        self.assertEqual(await self.run_job(expire_waitlist_offers, starts_at), 1)
        allocated, statuses = await self.state(session_id)
        self.assertEqual(allocated, 0)
        self.assertEqual(statuses[self.cat], WaitlistStatus.WAITING)

    async def test_no_show_after_the_check_in_window(self):
        member = await self.add_member("ann")
        session = await self.add(timetable_session(starts_at=NOW, minutes=60))
        rows = {
            status: Booking(
                user_id=member,
                timetable_session_id=session.id,
                resource_name=f"{status} class",
                resource_type=CLASS,
                starts_at=NOW,
                ends_at=NOW + 60 * MINUTE,
                status=status,
                created_at=NOW - timedelta(days=1),
            )
            for status in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN)
        }
        late = Booking(
            user_id=member,
            timetable_session_id=session.id,
            resource_name="Booked after the start",
            resource_type=CLASS,
            starts_at=NOW,
            ends_at=NOW + 60 * MINUTE,
            created_at=NOW + 5 * MINUTE,
        )
        # Made before timetable sessions existed, so it could never be checked in.
        legacy = Booking(
            user_id=member,
            resource_name="Legacy booking",
            resource_type=CLASS,
            starts_at=NOW - timedelta(days=1),
            created_at=NOW - timedelta(days=2),
        )
        await self.add(*rows.values(), late, legacy)
        self.assertEqual(await self.run_job(detect_no_shows, NOW + 9 * MINUTE), 0)
        self.assertEqual(await self.run_job(detect_no_shows, NOW + 10 * MINUTE), 1)
        self.assertEqual(await self.run_job(detect_no_shows, NOW + 15 * MINUTE), 1)
        async with self.sessions() as db:
            statuses = {
                item.resource_name: item.status for item in await db.scalars(select(Booking))
            }
        self.assertEqual(
            statuses,
            {
                "confirmed class": BookingStatus.NO_SHOW,
                "checked_in class": BookingStatus.CHECKED_IN,
                "Booked after the start": BookingStatus.NO_SHOW,
                "Legacy booking": BookingStatus.CONFIRMED,
            },
        )

    async def test_pool_no_show_releases_the_lane_to_the_waiting_list(self):
        pool = (MembershipEntitlement.POOL_BOOKING,)
        ann = await self.add_member("ann", pool)
        ben = await self.add_member("ben", pool)
        lane = timetable_session(POOL, starts_at=NOW, minutes=60)
        lane.allocated_count = 1
        await self.add(lane)
        await self.add(
            Booking(
                user_id=ann,
                timetable_session_id=lane.id,
                resource_name=lane.resource_name,
                resource_type=POOL,
                starts_at=lane.starts_at,
                ends_at=lane.ends_at,
                created_at=NOW - timedelta(days=1),
            ),
            WaitlistEntry(session_id=lane.id, user_id=ben),
        )
        self.assertEqual(await self.run_job(detect_no_shows, NOW + 10 * MINUTE), 1)
        allocated, statuses = await self.state(lane.id)
        self.assertEqual((allocated, statuses[ben]), (1, WaitlistStatus.OFFERED))

    async def test_three_no_shows_pause_new_bookings(self):
        member = await self.add_member("ann")
        for day in (1, 2, 3):
            missed = await self.add(timetable_session(starts_at=NOW - timedelta(days=day)))
            await self.add(
                Booking(
                    user_id=member,
                    timetable_session_id=missed.id,
                    resource_name=missed.resource_name,
                    resource_type=CLASS,
                    starts_at=missed.starts_at,
                    ends_at=missed.ends_at,
                    created_at=NOW - timedelta(days=10),
                )
            )
        self.assertEqual(await self.run_job(detect_no_shows, NOW), 3)
        session_id = (await self.add(timetable_session())).id
        with self.assertRaises(BookingEligibilityError) as raised:
            await self.book(session_id, member)
        self.assertEqual([item.code for item in raised.exception.failures], ["no_show_penalty"])


if __name__ == "__main__":
    unittest.main()
