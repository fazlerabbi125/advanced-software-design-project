"""What happens to equipment slots when their unit leaves service.

Each future slot on the unit moves to an in-service unit of the same type that is free
for that time, and its bookings follow it. A slot that cannot move keeps its unit: its
confirmed bookings are cancelled, its waiting list ends, and it cannot be booked again
until the unit is repaired. The caller locks the units and commits.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking, BookingStatus, WaitlistEntry, WaitlistStatus
from app.models.facilities import EquipmentUnit
from app.models.timetable_sessions import TimetableSession


@dataclass(frozen=True)
class MovedSlot:
    session_id: int
    from_unit: str
    to_unit: str
    member_ids: list[UUID]


@dataclass(frozen=True)
class CancelledBooking:
    booking_id: int
    session_id: int
    member_id: UUID


@dataclass
class OutageOutcome:
    """Who is affected, for the confirmation response and for notifications."""

    moved: list[MovedSlot] = field(default_factory=list)
    cancelled: list[CancelledBooking] = field(default_factory=list)


class UnitOutageHandler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle(self, unit: EquipmentUnit, now: datetime) -> OutageOutcome:
        outcome = OutageOutcome()
        slots = (
            await self.session.scalars(
                select(TimetableSession)
                .where(
                    TimetableSession.equipment_unit_id == unit.id,
                    TimetableSession.starts_at > now,
                )
                .order_by(TimetableSession.starts_at)
                .with_for_update()
            )
        ).all()
        if not slots:
            return outcome
        alternatives = (
            await self.session.scalars(
                select(EquipmentUnit)
                .where(
                    EquipmentUnit.equipment_type == unit.equipment_type,
                    EquipmentUnit.in_service.is_(True),
                    EquipmentUnit.id != unit.id,
                )
                .order_by(EquipmentUnit.id)
            )
        ).all()
        for slot in slots:
            target = await self._free_unit(alternatives, slot)
            if target is not None:
                outcome.moved.append(await self._move(slot, unit, target))
            else:
                outcome.cancelled.extend(await self._cancel(slot))
        return outcome

    async def _free_unit(
        self, candidates: list[EquipmentUnit], slot: TimetableSession
    ) -> EquipmentUnit | None:
        for candidate in candidates:
            clash = await self.session.scalar(
                select(TimetableSession.id).where(
                    TimetableSession.equipment_unit_id == candidate.id,
                    TimetableSession.starts_at < slot.ends_at,
                    TimetableSession.ends_at > slot.starts_at,
                )
            )
            if clash is None:
                return candidate
        return None

    async def _move(
        self, slot: TimetableSession, unit: EquipmentUnit, target: EquipmentUnit
    ) -> MovedSlot:
        slot.equipment_unit_id = target.id
        slot.resource_name = target.name
        await self.session.execute(
            update(Booking)
            .where(Booking.timetable_session_id == slot.id)
            .values(resource_name=target.name)
        )
        await self.session.flush()
        members = await self.session.scalars(
            select(Booking.user_id).where(
                Booking.timetable_session_id == slot.id,
                Booking.status == BookingStatus.CONFIRMED,
            )
        )
        return MovedSlot(slot.id, unit.name, target.name, list(members.all()))

    async def _cancel(self, slot: TimetableSession) -> list[CancelledBooking]:
        bookings = (
            await self.session.scalars(
                select(Booking)
                .where(
                    Booking.timetable_session_id == slot.id,
                    Booking.status == BookingStatus.CONFIRMED,
                )
                .with_for_update()
            )
        ).all()
        for booking in bookings:
            booking.status = BookingStatus.CANCELLED
        await self.session.execute(
            update(WaitlistEntry)
            .where(
                WaitlistEntry.session_id == slot.id,
                WaitlistEntry.status.in_((WaitlistStatus.WAITING, WaitlistStatus.OFFERED)),
            )
            .values(status=WaitlistStatus.EXPIRED)
        )
        slot.allocated_count = 0
        await self.session.flush()
        return [CancelledBooking(item.id, slot.id, item.user_id) for item in bookings]
