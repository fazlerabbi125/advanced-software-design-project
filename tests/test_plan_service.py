"""Manager plan configuration against a disposable PostgreSQL database.

BFS_TEST_DATABASE_URL=postgresql+asyncpg://... uv run python -m unittest discover -s tests -v
The tests create and drop their own schema within that database.
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
    BookingResourceType,
    Membership,
    MembershipEntitlement,
    MembershipStatus,
    PlanEntitlement,
    TimetableSession,
    User,
)
from app.modules.bookings.eligibility import BookingEligibilityError
from app.modules.bookings.service import BookingService
from app.modules.memberships.service import (
    MembershipService,
    PlanNameTakenError,
    PlanNotFoundError,
)
from tests.test_booking_eligibility import NOW

CLASS = MembershipEntitlement.CLASS_BOOKING
POOL = MembershipEntitlement.POOL_BOOKING
GYM = MembershipEntitlement.GYM_FLOOR_ACCESS


@unittest.skipUnless(os.getenv("BFS_TEST_DATABASE_URL"), "set a disposable BFS_TEST_DATABASE_URL")
class PlanServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "plan_test_" + uuid4().hex
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
        self.standard = await self.create(
            "Standard", price_minor=4500, window=3, limit=5, entitlements={GYM, CLASS, POOL}
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def create(self, name, price_minor=2500, window=1, limit=1, entitlements=(CLASS,)):
        async with self.sessions() as session:
            return await MembershipService(session).create_plan(
                name=name,
                price_minor=price_minor,
                currency="EUR",
                duration_days=30,
                booking_window_days=window,
                weekly_booking_limit=limit,
                entitlements=set(entitlements),
            )

    async def entitlements_of(self, plan_id):
        async with self.sessions() as session:
            rows = await session.scalars(
                select(PlanEntitlement.entitlement).where(PlanEntitlement.plan_id == plan_id)
            )
            return set(rows.all())

    async def test_created_plan_is_stored_and_on_sale(self):
        plan = await self.create("Student", window=2, limit=4, entitlements={GYM, CLASS})

        self.assertTrue(plan.is_active)
        self.assertEqual((plan.booking_window_days, plan.weekly_booking_limit), (2, 4))
        self.assertEqual(await self.entitlements_of(plan.id), {GYM, CLASS})
        async with self.sessions() as session:
            names = [item.name for item in await MembershipService(session).list_plans()]
        self.assertIn("Student", names)

    async def test_plan_names_are_unique_ignoring_case(self):
        with self.assertRaises(PlanNameTakenError):
            await self.create("standard")

    async def test_update_changes_only_given_fields_and_replaces_entitlements(self):
        async with self.sessions() as session:
            plan = await MembershipService(session).update_plan(
                self.standard.id, weekly_booking_limit=6, entitlements={GYM, POOL}
            )

        self.assertEqual(plan.weekly_booking_limit, 6)
        self.assertEqual(plan.booking_window_days, 3)
        self.assertEqual(plan.price_minor, 4500)
        self.assertEqual(await self.entitlements_of(plan.id), {GYM, POOL})

    async def test_rename_checks_other_plans_but_allows_a_case_change(self):
        await self.create("Student")
        async with self.sessions() as session:
            service = MembershipService(session)
            with self.assertRaises(PlanNameTakenError):
                await service.update_plan(self.standard.id, name="STUDENT")
            plan = await service.update_plan(self.standard.id, name="STANDARD")
        self.assertEqual(plan.name, "STANDARD")

    async def test_unknown_plan_and_unknown_fields_are_refused(self):
        async with self.sessions() as session:
            service = MembershipService(session)
            with self.assertRaises(PlanNotFoundError):
                await service.update_plan(99999, weekly_booking_limit=1)
            with self.assertRaises(ValueError):
                await service.update_plan(self.standard.id, id=5)
            with self.assertRaises(PlanNotFoundError):
                await service.deactivate_plan(99999)

    async def test_deactivated_plan_is_off_sale_but_listed_for_managers(self):
        async with self.sessions() as session:
            service = MembershipService(session)
            await service.deactivate_plan(self.standard.id)
            on_sale = [plan.id for plan in await service.list_plans()]
            everything = {plan.id: plan.is_active for plan in await service.list_all_plans()}
        self.assertNotIn(self.standard.id, on_sale)
        self.assertEqual(everything[self.standard.id], False)

    async def test_new_plan_is_enforced_by_booking_rules_without_code_changes(self):
        student = await self.create("Student", window=1, limit=1, entitlements={CLASS})
        async with self.sessions() as session:
            user = User(email="student@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            session.add(
                Membership(
                    user_id=user.id,
                    plan_id=student.id,
                    status=MembershipStatus.ACTIVE,
                    starts_on=NOW.date(),
                    ends_on=(NOW + timedelta(days=29)).date(),
                )
            )
            await session.commit()
            user_id = user.id

        async def book(resource_type, days_ahead, minutes=0):
            starts_at = NOW + timedelta(days=days_ahead, minutes=minutes)
            async with self.sessions() as session:
                timetable_session = TimetableSession(
                    resource_name="Session",
                    resource_type=resource_type,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=45),
                    capacity=10,
                )
                session.add(timetable_session)
                await session.commit()
                return await BookingService(session).create(user_id, timetable_session.id)

        with patch("app.modules.bookings.service.utc_now", return_value=NOW):
            await book(BookingResourceType.CLASS, days_ahead=0, minutes=60)
            with self.assertRaises(BookingEligibilityError) as raised:
                await book(BookingResourceType.POOL, days_ahead=2)
        self.assertEqual(
            {item.code for item in raised.exception.failures},
            {"plan_entitlement", "booking_window", "weekly_limit"},
        )


if __name__ == "__main__":
    unittest.main()
