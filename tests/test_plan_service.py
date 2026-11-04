"""Manager plan configuration against a disposable PostgreSQL database.

BFS_TEST_DATABASE_URL=postgresql+asyncpg://... uv run python -m unittest discover -s tests -v
The tests create and drop their own schema within that database.
"""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import (
    Base,
    BookingResourceType,
    Membership,
    MembershipEntitlement,
    MembershipStatus,
    PlanEntitlement,
    StripeEvent,
    TimetableSession,
    User,
)
from app.modules.bookings.service import BookingService
from app.modules.memberships.payment_gateway import PaymentResult, PaymentStatus
from app.modules.memberships.service import MembershipService
from app.modules.payments.service import StripeWebhookService
from app.shared.pagination import PageParams
from tests.test_booking_eligibility import NOW

CLASS = MembershipEntitlement.CLASS_BOOKING
POOL = MembershipEntitlement.POOL_BOOKING
GYM = MembershipEntitlement.GYM_FLOOR_ACCESS


class PendingPaymentGateway:
    def __init__(self, reference="checkout_test"):
        self.reference = reference

    async def create_checkout(self, amount_minor, currency, *, plan_name):
        return PaymentResult(
            reference=self.reference,
            status=PaymentStatus.PENDING,
            amount_minor=amount_minor,
            currency=currency,
        )


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
            plan = await MembershipService().create_plan(
                session,
                name=name,
                price_minor=price_minor,
                currency="EUR",
                duration_days=30,
                booking_window_days=window,
                weekly_booking_limit=limit,
                entitlements=set(entitlements),
            )
            await session.commit()
            return plan

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
            names = [
                item.name
                for item in (
                    await MembershipService().list_plans(session, PageParams(page=1, limit=20))
                ).items
            ]
        self.assertIn("Student", names)

    async def test_plan_names_are_unique_ignoring_case(self):
        with self.assertRaises(AppError):
            await self.create("standard")

    async def test_update_changes_only_given_fields_and_replaces_entitlements(self):
        async with self.sessions() as session:
            plan = await MembershipService().update_plan(
                session, self.standard.id, weekly_booking_limit=6, entitlements={GYM, POOL}
            )
            await session.commit()

        self.assertEqual(plan.weekly_booking_limit, 6)
        self.assertEqual(plan.booking_window_days, 3)
        self.assertEqual(plan.price_minor, 4500)
        self.assertEqual(await self.entitlements_of(plan.id), {GYM, POOL})

    async def test_rename_checks_other_plans_but_allows_a_case_change(self):
        await self.create("Student")
        async with self.sessions() as session:
            service = MembershipService()
            with self.assertRaises(AppError):
                await service.update_plan(session, self.standard.id, name="STUDENT")
            plan = await service.update_plan(session, self.standard.id, name="STANDARD")
            await session.commit()
        self.assertEqual(plan.name, "STANDARD")

    async def test_unknown_plan_and_unknown_fields_are_refused(self):
        async with self.sessions() as session:
            service = MembershipService()
            with self.assertRaises(AppError):
                await service.update_plan(session, 99999, weekly_booking_limit=1)
            with self.assertRaises(AppError):
                await service.update_plan(session, self.standard.id, id=5)
            with self.assertRaises(AppError):
                await service.deactivate_plan(session, 99999)

    async def test_deactivated_plan_is_off_sale_but_listed_for_managers(self):
        async with self.sessions() as session:
            service = MembershipService()
            await service.deactivate_plan(session, self.standard.id)
            await session.commit()
            on_sale = [
                plan.id
                for plan in (await service.list_plans(session, PageParams(page=1, limit=20))).items
            ]
            everything = {
                plan.id: plan.is_active
                for plan in (
                    await service.list_all_plans(session, PageParams(page=1, limit=20))
                ).items
            }
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
                booking = await BookingService(MembershipService()).create(
                    session, [], user_id, timetable_session.id
                )
                await session.commit()
                return booking

        with patch("app.modules.bookings.service.utc_now", return_value=NOW):
            await book(BookingResourceType.CLASS, days_ahead=0, minutes=60)
            with self.assertRaises(AppError) as raised:
                await book(BookingResourceType.POOL, days_ahead=2)
        self.assertEqual(
            {item.code for item in raised.exception.failures},
            {"plan_entitlement", "booking_window", "weekly_limit"},
        )

    async def test_cancellation_revokes_overlapping_active_renewals(self):
        today = datetime.now(UTC).date()
        async with self.sessions() as session:
            user = User(email="renewal@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            original = Membership(
                user_id=user.id,
                plan_id=self.standard.id,
                status=MembershipStatus.ACTIVE,
                starts_on=today - timedelta(days=10),
                ends_on=today + timedelta(days=20),
            )
            renewed = Membership(
                user_id=user.id,
                plan_id=self.standard.id,
                status=MembershipStatus.ACTIVE,
                starts_on=original.starts_on,
                ends_on=today + timedelta(days=50),
            )
            session.add_all((original, renewed))
            await session.commit()
            user_id = user.id
            renewed_id = renewed.id

        async with self.sessions() as session:
            service = MembershipService()
            cancelled = await service.cancel(session, [], user_id)
            await session.commit()

        self.assertEqual(cancelled.id, renewed_id)
        async with self.sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Membership)
                        .where(Membership.user_id == user_id)
                        .order_by(Membership.id)
                    )
                ).all()
            )
            service = MembershipService()
            self.assertEqual([row.status for row in rows], [MembershipStatus.CANCELLED] * 2)
            self.assertFalse(await service.has_active_membership(session, user_id, today))
            self.assertFalse(await service.has_entitlement(session, user_id, GYM, today))

            purchased = await MembershipService(PendingPaymentGateway()).purchase(
                session, user_id, self.standard.id
            )
            self.assertEqual(purchased.membership.status, MembershipStatus.PENDING)

    async def test_paid_early_renewal_supersedes_predecessor_and_is_idempotent(self):
        today = datetime.now(UTC).date()
        async with self.sessions() as session:
            user = User(email="renew-success@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            predecessor = Membership(
                user_id=user.id,
                plan_id=self.standard.id,
                status=MembershipStatus.ACTIVE,
                starts_on=today - timedelta(days=10),
                ends_on=today + timedelta(days=20),
            )
            session.add(predecessor)
            await session.commit()
            user_id = user.id
            predecessor_id = predecessor.id

        async with self.sessions() as session:
            renewal = await MembershipService(PendingPaymentGateway("checkout-success")).renew(
                session, user_id
            )
            await session.commit()
            renewal_id = renewal.membership.id
            self.assertEqual(renewal.membership.renewed_from_membership_id, predecessor_id)

        async with self.sessions() as session:
            outcome = await StripeWebhookService().process_checkout(
                session,
                [],
                stripe_event_id="event-success",
                stripe_session_id="checkout-success",
                payment_succeeded=True,
            )
            await session.commit()
        self.assertEqual(outcome, "activated")

        async with self.sessions() as session:
            predecessor = await session.get(Membership, predecessor_id)
            renewal = await session.get(Membership, renewal_id)
            self.assertEqual(predecessor.status, MembershipStatus.CANCELLED)
            self.assertEqual(renewal.status, MembershipStatus.ACTIVE)
            duplicate = await StripeWebhookService().process_checkout(
                session,
                [],
                stripe_event_id="event-success",
                stripe_session_id="checkout-success",
                payment_succeeded=True,
            )
            self.assertEqual(duplicate, "ignored")
            self.assertEqual(len((await session.scalars(select(StripeEvent))).all()), 1)

    async def test_failed_early_renewal_keeps_predecessor_active(self):
        today = datetime.now(UTC).date()
        async with self.sessions() as session:
            user = User(email="renew-failure@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            predecessor = Membership(
                user_id=user.id,
                plan_id=self.standard.id,
                status=MembershipStatus.ACTIVE,
                starts_on=today - timedelta(days=10),
                ends_on=today + timedelta(days=20),
            )
            session.add(predecessor)
            await session.commit()
            user_id = user.id
            predecessor_id = predecessor.id

        async with self.sessions() as session:
            renewal = await MembershipService(PendingPaymentGateway("checkout-failure")).renew(
                session, user_id
            )
            await session.commit()
            renewal_id = renewal.membership.id

        async with self.sessions() as session:
            outcome = await StripeWebhookService().process_checkout(
                session,
                [],
                stripe_event_id="event-failure",
                stripe_session_id="checkout-failure",
                payment_succeeded=False,
            )
            await session.commit()
        self.assertEqual(outcome, "cancelled")

        async with self.sessions() as session:
            predecessor = await session.get(Membership, predecessor_id)
            renewal = await session.get(Membership, renewal_id)
            self.assertEqual(predecessor.status, MembershipStatus.ACTIVE)
            self.assertEqual(renewal.status, MembershipStatus.CANCELLED)

    async def test_expired_renewal_has_no_predecessor_link(self):
        today = datetime.now(UTC).date()
        async with self.sessions() as session:
            user = User(email="renew-expired@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            expired = Membership(
                user_id=user.id,
                plan_id=self.standard.id,
                status=MembershipStatus.EXPIRED,
                starts_on=today - timedelta(days=40),
                ends_on=today - timedelta(days=10),
            )
            session.add(expired)
            await session.commit()
            user_id = user.id

        async with self.sessions() as session:
            renewal = await MembershipService(PendingPaymentGateway("checkout-expired")).renew(
                session, user_id
            )

        self.assertIsNone(renewal.membership.renewed_from_membership_id)


if __name__ == "__main__":
    unittest.main()
