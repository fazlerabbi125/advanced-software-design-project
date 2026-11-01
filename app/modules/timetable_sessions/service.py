from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.bookings import BookingResourceType
from app.models.facilities import EquipmentUnit
from app.models.timetable_sessions import TimetableSession
from app.modules.timetable_sessions.schemas import (
    CreateSessionRequest,
    GenerateEquipmentSlotsRequest,
)
from app.shared.constants import EQUIPMENT_SLOT_CAPACITY
from app.shared.helpers import utc_now
from app.shared.pagination import (
    CursorDirection,
    CursorMeta,
    CursorParams,
    CursorResult,
    encode_cursor,
)


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
                raise AppError(
                    f"{resource_name} already has a slot at that time", HTTPStatus.CONFLICT
                )
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
                    capacity=EQUIPMENT_SLOT_CAPACITY,
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
            raise AppError("equipment unit was not found", HTTPStatus.NOT_FOUND)
        if not unit.in_service:
            raise AppError(f"{unit.name} is out of service", HTTPStatus.CONFLICT)
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
        self, session: AsyncSession, params: CursorParams, after: datetime | None = None
    ) -> CursorResult[TimetableSession]:
        """Sessions that have not ended yet, soonest first."""
        statement = (
            select(TimetableSession)
            .outerjoin(EquipmentUnit, TimetableSession.equipment_unit_id == EquipmentUnit.id)
            .where(TimetableSession.ends_at > (after or utc_now()))
            .where(
                or_(
                    TimetableSession.equipment_unit_id.is_(None), EquipmentUnit.in_service.is_(True)
                )
            )
        )
        if params.values:
            if len(params.values) != 2 or not isinstance(params.values[0], str):
                raise AppError("cursor is invalid", HTTPStatus.UNPROCESSABLE_ENTITY)
            try:
                starts_at = datetime.fromisoformat(params.values[0])
                session_id = int(params.values[1])
            except (TypeError, ValueError) as error:
                raise AppError("cursor is invalid", HTTPStatus.UNPROCESSABLE_ENTITY) from error
            if params.direction == CursorDirection.NEXT:
                statement = statement.where(
                    (TimetableSession.starts_at > starts_at)
                    | (
                        (TimetableSession.starts_at == starts_at)
                        & (TimetableSession.id > session_id)
                    )
                ).order_by(TimetableSession.starts_at, TimetableSession.id)
            else:
                statement = statement.where(
                    (TimetableSession.starts_at < starts_at)
                    | (
                        (TimetableSession.starts_at == starts_at)
                        & (TimetableSession.id < session_id)
                    )
                ).order_by(TimetableSession.starts_at.desc(), TimetableSession.id.desc())
        elif params.direction == CursorDirection.PREVIOUS:
            raise AppError(
                "cursor is required for previous navigation", HTTPStatus.UNPROCESSABLE_ENTITY
            )
        else:
            statement = statement.order_by(TimetableSession.starts_at, TimetableSession.id)
        rows = list((await session.scalars(statement.limit(params.limit + 1))).all())
        has_more = len(rows) > params.limit
        items = rows[: params.limit]
        if params.direction == CursorDirection.PREVIOUS:
            items.reverse()
        has_next = (
            has_more if params.direction == CursorDirection.NEXT else params.cursor is not None
        )
        has_previous = (
            params.cursor is not None if params.direction == CursorDirection.NEXT else has_more
        )
        return CursorResult(
            items=items,
            meta=CursorMeta(
                limit=params.limit,
                next_cursor=(
                    encode_cursor(items[-1].starts_at.isoformat(), items[-1].id)
                    if has_next and items
                    else None
                ),
                previous_cursor=(
                    encode_cursor(items[0].starts_at.isoformat(), items[0].id)
                    if has_previous and items
                    else None
                ),
                has_next=has_next,
                has_previous=has_previous,
            ),
        )
