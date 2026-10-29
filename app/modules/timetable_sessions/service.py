from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.bookings import BookingResourceType
from app.models.facilities import EquipmentUnit
from app.models.timetable_sessions import TimetableSession
from app.modules.timetable_sessions.schemas import (
    CreateSessionRequest,
    GenerateEquipmentSlotsRequest,
)
from app.shared.helpers import utc_now


class TimetableService:
    async def create(
        self, session: AsyncSession, payload: CreateSessionRequest
    ) -> TimetableSession:
        starts_at = payload.starts_at.astimezone(UTC)
        ends_at = payload.ends_at.astimezone(UTC)
        resource_name = payload.resource_name.strip()
        if payload.equipment_unit_id is not None:
            unit = await self._locked_unit_in_service(session, payload.equipment_unit_id)
            resource_name = unit.name
            if await self._unit_has_slot(session, unit.id, starts_at, ends_at):
                raise AppError(f"{resource_name} already has a slot at that time", 409)
        timetable_session = TimetableSession(
            resource_name=resource_name,
            resource_type=payload.resource_type,
            starts_at=starts_at,
            ends_at=ends_at,
            capacity=payload.capacity,
            allocated_count=0,
            station_count=payload.station_count,
            equipment_unit_id=payload.equipment_unit_id,
        )
        session.add(timetable_session)
        await session.flush()
        return timetable_session

    async def generate_equipment_slots(
        self, session: AsyncSession, payload: GenerateEquipmentSlotsRequest
    ) -> list[TimetableSession]:
        unit = await self._locked_unit_in_service(session, payload.equipment_unit_id)
        length = timedelta(minutes=payload.slot_minutes)
        starts_at = payload.starts_at.astimezone(UTC)
        ends_at = payload.ends_at.astimezone(UTC)
        created: list[TimetableSession] = []
        while starts_at + length <= ends_at:
            if not await self._unit_has_slot(session, unit.id, starts_at, starts_at + length):
                slot = TimetableSession(
                    resource_name=unit.name,
                    resource_type=BookingResourceType.EQUIPMENT,
                    starts_at=starts_at,
                    ends_at=starts_at + length,
                    capacity=1,
                    allocated_count=0,
                    equipment_unit_id=unit.id,
                )
                session.add(slot)
                created.append(slot)
            starts_at += length
        await session.flush()
        return created

    async def _locked_unit_in_service(self, session: AsyncSession, unit_id: int) -> EquipmentUnit:
        unit = await session.scalar(
            select(EquipmentUnit).where(EquipmentUnit.id == unit_id).with_for_update()
        )
        if unit is None:
            raise AppError("equipment unit was not found", 404)
        if not unit.in_service:
            raise AppError(f"{unit.name} is out of service", 409)
        return unit

    async def _unit_has_slot(
        self, session: AsyncSession, unit_id: int, starts_at: datetime, ends_at: datetime
    ) -> bool:
        clash = await session.scalar(
            select(TimetableSession.id).where(
                TimetableSession.equipment_unit_id == unit_id,
                TimetableSession.starts_at < ends_at,
                TimetableSession.ends_at > starts_at,
            )
        )
        return clash is not None

    async def upcoming(
        self, session: AsyncSession, after: datetime | None = None
    ) -> list[TimetableSession]:
        """Sessions that have not ended yet, soonest first."""
        statement = (
            select(TimetableSession)
            .where(TimetableSession.ends_at > (after or utc_now()))
            .order_by(TimetableSession.starts_at, TimetableSession.id)
        )
        return list((await session.scalars(statement)).all())
