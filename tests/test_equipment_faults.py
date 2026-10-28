"""Equipment faults, affected slots, equipment slots on the timetable and the daily cap.

The database tests use an explicitly supplied disposable PostgreSQL database:
BFS_TEST_DATABASE_URL=postgresql+asyncpg://... uv run python -m unittest discover -s tests -v
"""

import asyncio
import os
import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Base,
    Booking,
    BookingResourceType,
    BookingStatus,
    EquipmentUnit,
    FaultStatus,
    MembershipEntitlement,
    TimetableSession,
    User,
    UserRole,
    WaitlistEntry,
    WaitlistStatus,
)
from app.modules.bookings.eligibility import (
    BookingContext,
    BookingEligibilityError,
    build_eligibility_chain,
)
from app.modules.bookings.outages import UnitOutageHandler
from app.modules.bookings.service import (
    BookingService,
    BookingStateError,
    SessionFullError,
    offer_deadline,
)
from app.modules.facilities.service import (
    FacilitiesService,
    FaultStateError,
    UnitNameTakenError,
    normalise_equipment_type,
)
from app.modules.timetable_sessions.schemas import (
    CreateSessionRequest,
    GenerateEquipmentSlotsRequest,
)
from app.modules.timetable_sessions.service import EquipmentUnavailableError, TimetableService
from tests.test_booking_eligibility import NOW, membership

EQUIPMENT = BookingResourceType.EQUIPMENT
GYM = (MembershipEntitlement.GYM_FLOOR_ACCESS,)
HOUR = timedelta(hours=1)


class EquipmentRuleTests(unittest.TestCase):
    def setUp(self):
        self.context = BookingContext(
            NOW, NOW + HOUR, EQUIPMENT, membership(limit=10, entitlements=GYM), []
        )

    def codes(self, **changes):
        return [
            failure.code
            for failure in build_eligibility_chain().handle(replace(self.context, **changes))
        ]

    def test_equipment_needs_only_gym_floor_access(self):
        self.assertEqual(self.codes(), [])
        self.assertEqual(self.codes(membership=membership(entitlements=())), ["plan_entitlement"])

    def test_two_slots_of_a_type_per_day(self):
        self.assertEqual(self.codes(equipment_slots_that_day=1), [])
        self.assertEqual(self.codes(equipment_slots_that_day=2), ["equipment_daily_cap"])
        # The cap is for equipment only.
        self.assertEqual(
            self.codes(
                resource_type=BookingResourceType.CLASS,
                membership=membership(entitlements=(MembershipEntitlement.CLASS_BOOKING,)),
                equipment_slots_that_day=5,
            ),
            [],
        )

    def test_equipment_offer_ends_fifteen_minutes_before_the_end(self):
        slot = TimetableSession(
            resource_type=EQUIPMENT, starts_at=NOW, ends_at=NOW + timedelta(minutes=30)
        )
        self.assertEqual(offer_deadline(NOW, slot), NOW + timedelta(minutes=15))

    def test_equipment_types_are_normalised(self):
        self.assertEqual(normalise_equipment_type("  Squat   Rack "), "squat_rack")

    def test_equipment_slot_requests_are_checked(self):
        slot = {
            "resource_name": "ignored",
            "resource_type": "equipment",
            "starts_at": NOW,
            "ends_at": NOW + HOUR,
            "capacity": 1,
            "equipment_unit_id": 1,
        }
        CreateSessionRequest(**slot)
        for change in (
            {"equipment_unit_id": None},
            {"capacity": 2},
            {"resource_type": "class"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CreateSessionRequest(**(slot | change))
        with self.assertRaises(ValidationError):
            GenerateEquipmentSlotsRequest(
                equipment_unit_id=1, starts_at=NOW, ends_at=NOW + timedelta(days=2), slot_minutes=30
            )


@unittest.skipUnless(os.getenv("BFS_TEST_DATABASE_URL"), "set a disposable BFS_TEST_DATABASE_URL")
class EquipmentFaultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "equipment_test_" + uuid4().hex
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
        async with self.sessions() as session:
            staff = User(email="staff@example.test", password_hash="unused", role=UserRole.STAFF)
            session.add(staff)
            await session.commit()
            self.staff_id = staff.id
        self.rack1 = await self.add_unit("Squat Rack 1")
        self.rack2 = await self.add_unit("Squat Rack 2")
        self.bike = await self.add_unit("Bike 1", "bike")

    async def asyncTearDown(self):
        self.clock.stop()
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def add_unit(self, name, equipment_type="Squat rack"):
        async with self.sessions() as session:
            unit = await FacilitiesService(session).register_unit(name, equipment_type, "gym_floor")
            return unit.id

    async def add_member(self, name):
        async with self.sessions() as session:
            user = User(email=f"{name}@example.test", password_hash="unused")
            session.add(user)
            await session.flush()
            member = membership(limit=10, entitlements=GYM)
            member.user_id = user.id
            member.plan.name = name
            member.plan.price_minor = 3000
            session.add(member)
            await session.commit()
            return user.id

    async def add_slot(self, unit_id, starts_at=NOW + HOUR, minutes=60):
        async with self.sessions() as session:
            slot = await TimetableService(session).create(
                CreateSessionRequest(
                    resource_name="ignored",
                    resource_type=EQUIPMENT,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=minutes),
                    capacity=1,
                    equipment_unit_id=unit_id,
                )
            )
            await session.commit()
            return slot.id

    async def book(self, slot_id, user_id):
        async with self.sessions() as session:
            return await BookingService(session).create(user_id, slot_id)

    async def report(self, unit_id, text_="The safety catch is bent"):
        async with self.sessions() as session:
            fault = await FacilitiesService(session).report_fault(unit_id, self.staff_id, text_)
            return fault.id

    async def confirm(self, fault_id, now=NOW):
        """What the confirm endpoint does: one transaction for the fault and the slots."""
        async with self.sessions() as session:
            facilities = FacilitiesService(session)
            fault, unit = await facilities.confirm_fault(fault_id, self.staff_id, now)
            outcome = await UnitOutageHandler(session).handle(unit, now)
            await facilities.save(fault)
            return outcome

    async def get(self, model, row_id):
        async with self.sessions() as session:
            return await session.get(model, row_id)

    async def test_confirmed_fault_moves_slots_to_a_free_unit_of_the_same_type(self):
        ann = await self.add_member("ann")
        slot_id = await self.add_slot(self.rack1)
        booking = await self.book(slot_id, ann)
        self.assertEqual(booking.resource_name, "Squat Rack 1")

        outcome = await self.confirm(await self.report(self.rack1))

        self.assertEqual(
            [
                (item.session_id, item.from_unit, item.to_unit, item.member_ids)
                for item in outcome.moved
            ],
            [(slot_id, "Squat Rack 1", "Squat Rack 2", [ann])],
        )
        self.assertEqual(outcome.cancelled, [])
        slot = await self.get(TimetableSession, slot_id)
        self.assertEqual((slot.equipment_unit_id, slot.resource_name), (self.rack2, "Squat Rack 2"))
        moved = await self.get(Booking, booking.id)
        self.assertEqual(
            (moved.status, moved.resource_name), (BookingStatus.CONFIRMED, "Squat Rack 2")
        )
        self.assertFalse((await self.get(EquipmentUnit, self.rack1)).in_service)

    async def test_without_a_free_unit_bookings_are_cancelled_until_repair(self):
        ann, ben, cat = [await self.add_member(name) for name in ("ann", "ben", "cat")]
        await self.book(await self.add_slot(self.rack2), ben)
        slot_id = await self.add_slot(self.rack1)
        booking = await self.book(slot_id, ann)
        with self.assertRaises(SessionFullError):
            await self.book(slot_id, cat)

        fault_id = await self.report(self.rack1)
        outcome = await self.confirm(fault_id)

        self.assertEqual(outcome.moved, [])
        self.assertEqual(
            [(item.booking_id, item.member_id) for item in outcome.cancelled], [(booking.id, ann)]
        )
        self.assertEqual((await self.get(Booking, booking.id)).status, BookingStatus.CANCELLED)
        self.assertEqual((await self.get(TimetableSession, slot_id)).allocated_count, 0)
        async with self.sessions() as session:
            entry = await session.scalar(select(WaitlistEntry).where(WaitlistEntry.user_id == cat))
            self.assertEqual(entry.status, WaitlistStatus.EXPIRED)
        with self.assertRaisesRegex(BookingStateError, "out of service"):
            await self.book(slot_id, ann)

        async with self.sessions() as session:
            fault = await FacilitiesService(session).resolve_fault(fault_id, self.staff_id)
        self.assertEqual(fault.status, FaultStatus.RESOLVED)
        rebooked = await self.book(slot_id, ann)
        self.assertEqual(rebooked.status, BookingStatus.CONFIRMED)

    async def test_slots_that_have_started_and_other_types_are_left_alone(self):
        started = await self.add_slot(self.rack1, starts_at=NOW - timedelta(minutes=10))
        bike_slot = await self.add_slot(self.bike)
        outcome = await self.confirm(await self.report(self.rack1))
        self.assertEqual((outcome.moved, outcome.cancelled), ([], []))
        self.assertEqual((await self.get(TimetableSession, started)).equipment_unit_id, self.rack1)
        self.assertEqual((await self.get(TimetableSession, bike_slot)).equipment_unit_id, self.bike)

    async def test_fault_workflow_states(self):
        first, second = await self.report(self.rack1), await self.report(self.rack1)
        await self.confirm(first)
        await self.confirm(second)
        with self.assertRaises(FaultStateError):
            await self.confirm(first)
        async with self.sessions() as session:
            service = FacilitiesService(session)
            await service.resolve_fault(first, self.staff_id)
            # Still out of service: the second confirmed fault is open.
            self.assertFalse((await service.get_unit(self.rack1)).in_service)
            await service.resolve_fault(second, self.staff_id)
            self.assertTrue((await service.get_unit(self.rack1)).in_service)
            dismissed = await service.dismiss_fault(await self.report(self.bike), self.staff_id)
            self.assertEqual(dismissed.status, FaultStatus.DISMISSED)
            with self.assertRaises(FaultStateError):
                await service.resolve_fault(dismissed.id, self.staff_id)
            reported = await self.report(self.bike)
            self.assertEqual(
                [item.id for item in await service.list_faults(FaultStatus.REPORTED)], [reported]
            )

    async def test_same_unit_name_registered_twice_at_once_is_a_clean_conflict(self):
        results = await asyncio.gather(
            self.add_unit("Bench 1", "bench"),
            self.add_unit("bench 1", "bench"),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(item, int) for item in results), 1)
        self.assertEqual(sum(isinstance(item, UnitNameTakenError) for item in results), 1)

    async def test_two_faults_confirmed_at_once_cannot_share_the_last_free_unit(self):
        rack3 = await self.add_unit("Squat Rack 3")
        ann, ben = await self.add_member("ann"), await self.add_member("ben")
        await self.book(await self.add_slot(self.rack1), ann)
        await self.book(await self.add_slot(self.rack2), ben)
        faults = [await self.report(self.rack1), await self.report(self.rack2)]

        outcomes = await asyncio.gather(*(self.confirm(fault) for fault in faults))

        moved = [item for outcome in outcomes for item in outcome.moved]
        cancelled = [item for outcome in outcomes for item in outcome.cancelled]
        self.assertEqual([item.to_unit for item in moved], ["Squat Rack 3"])
        self.assertEqual(len(cancelled), 1)
        async with self.sessions() as session:
            on_rack3 = await session.scalars(
                select(TimetableSession).where(TimetableSession.equipment_unit_id == rack3)
            )
            self.assertEqual(len(on_rack3.all()), 1)

    async def test_two_slots_of_a_type_per_day(self):
        ann = await self.add_member("ann")
        for hours in (1, 3):
            await self.book(await self.add_slot(self.rack1, NOW + hours * HOUR), ann)
        third = await self.add_slot(self.rack2, NOW + 5 * HOUR)
        with self.assertRaises(BookingEligibilityError) as raised:
            await self.book(third, ann)
        self.assertEqual([item.code for item in raised.exception.failures], ["equipment_daily_cap"])
        # Another equipment type, or the next day, is fine.
        await self.book(await self.add_slot(self.bike, NOW + 5 * HOUR), ann)
        await self.book(await self.add_slot(self.rack2, NOW + timedelta(days=1)), ann)

    async def test_equipment_slots_on_the_timetable(self):
        await self.add_slot(self.rack1, NOW + HOUR)
        with self.assertRaisesRegex(EquipmentUnavailableError, "already has a slot"):
            await self.add_slot(self.rack1, NOW + timedelta(minutes=90))
        async with self.sessions() as session:
            slots = await TimetableService(session).generate_equipment_slots(
                GenerateEquipmentSlotsRequest(
                    equipment_unit_id=self.rack1,
                    starts_at=NOW,
                    ends_at=NOW + 3 * HOUR,
                    slot_minutes=30,
                )
            )
            await session.commit()
        # 12:00-15:00 in 30-minute slots, skipping the existing 13:00-14:00 slot.
        self.assertEqual(
            [slot.starts_at.astimezone(NOW.tzinfo).strftime("%H:%M") for slot in slots],
            ["12:00", "12:30", "14:00", "14:30"],
        )
        self.assertTrue(all(slot.resource_name == "Squat Rack 1" for slot in slots))
        await self.confirm(await self.report(self.bike))
        with self.assertRaisesRegex(EquipmentUnavailableError, "out of service"):
            await self.add_slot(self.bike, NOW + HOUR)


if __name__ == "__main__":
    unittest.main()
