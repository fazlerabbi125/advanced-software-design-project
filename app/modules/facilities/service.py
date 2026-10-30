"""Equipment units and the fault workflow: reported, then confirmed or dismissed, then resolved.

The service never touches bookings. Confirming a fault takes the unit out of service and
leaves the transaction open, so the caller can move or cancel the unit's future slots
(bookings module) and commit both together.
"""

from datetime import datetime
from http import HTTPStatus
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.facilities import EquipmentFault, EquipmentUnit, FaultStatus
from app.shared.helpers import utc_now
from app.shared.pagination import PageMeta, PageParams, PageResult


def normalise_equipment_type(value: str) -> str:
    """'Squat rack' and 'squat_rack' name the same type."""
    return "_".join(value.strip().lower().split())


class FacilitiesService:
    async def register_unit(
        self, session: AsyncSession, name: str, equipment_type: str, zone: str
    ) -> EquipmentUnit:
        name = name.strip()
        taken = await session.scalar(
            select(EquipmentUnit.id).where(func.lower(EquipmentUnit.name) == name.lower())
        )
        if taken is not None:
            raise AppError(f"a unit called {name!r} already exists", HTTPStatus.CONFLICT)
        unit = EquipmentUnit(
            name=name, equipment_type=normalise_equipment_type(equipment_type), zone=zone
        )
        session.add(unit)
        try:
            await session.flush()
        except IntegrityError as error:
            # Another request registered the same name between the check and the insert.
            raise AppError(f"a unit called {name!r} already exists", HTTPStatus.CONFLICT) from error
        return unit

    async def list_units(
        self, session: AsyncSession, params: PageParams, equipment_type: str | None = None
    ) -> PageResult[EquipmentUnit]:
        filters = []
        if equipment_type is not None:
            filters.append(EquipmentUnit.equipment_type == normalise_equipment_type(equipment_type))
        total_count = (
            await session.scalar(select(func.count(EquipmentUnit.id)).where(*filters)) or 0
        )
        statement = (
            select(EquipmentUnit)
            .where(*filters)
            .order_by(EquipmentUnit.equipment_type, EquipmentUnit.name, EquipmentUnit.id)
            .offset(params.offset)
            .limit(params.limit)
        )
        return PageResult(
            items=list((await session.scalars(statement)).all()),
            meta=PageMeta(
                page=params.page,
                limit=params.limit,
                total_pages=(total_count + params.limit - 1) // params.limit,
                total_count=total_count,
            ),
        )

    async def get_unit(self, session: AsyncSession, unit_id: int) -> EquipmentUnit:
        unit = await session.get(EquipmentUnit, unit_id)
        if unit is None:
            raise AppError("equipment unit was not found", HTTPStatus.NOT_FOUND)
        return unit

    async def report_fault(
        self, session: AsyncSession, unit_id: int, reporter_id: UUID, description: str
    ) -> EquipmentFault:
        await self.get_unit(session, unit_id)
        fault = EquipmentFault(
            unit_id=unit_id,
            reported_by_id=reporter_id,
            description=description.strip(),
            status=FaultStatus.REPORTED,
        )
        session.add(fault)
        await session.flush()
        return fault

    async def list_faults(
        self, session: AsyncSession, params: PageParams, status: FaultStatus | None = None
    ) -> PageResult[EquipmentFault]:
        filters = []
        if status is not None:
            filters.append(EquipmentFault.status == status)
        total_count = (
            await session.scalar(select(func.count(EquipmentFault.id)).where(*filters)) or 0
        )
        statement = (
            select(EquipmentFault)
            .where(*filters)
            .order_by(EquipmentFault.created_at.desc(), EquipmentFault.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        return PageResult(
            items=list((await session.scalars(statement)).all()),
            meta=PageMeta(
                page=params.page,
                limit=params.limit,
                total_pages=(total_count + params.limit - 1) // params.limit,
                total_count=total_count,
            ),
        )

    async def confirm_fault(
        self, session: AsyncSession, fault_id: int, staff_id: UUID, now: datetime | None = None
    ) -> tuple[EquipmentFault, EquipmentUnit]:
        """Confirm a reported fault and take its unit out of service. Does not commit.

        Every unit of the same type is locked first, in id order, so two faults confirmed
        at once cannot move slots onto the same unit or deadlock on each other.
        """
        fault = await self._locked_fault(session, fault_id, FaultStatus.REPORTED)
        unit = await session.get(EquipmentUnit, fault.unit_id)
        await session.execute(
            select(EquipmentUnit.id)
            .where(EquipmentUnit.equipment_type == unit.equipment_type)
            .order_by(EquipmentUnit.id)
            .with_for_update()
        )
        await session.refresh(unit)
        fault.status = FaultStatus.CONFIRMED
        fault.reviewed_by_id = staff_id
        fault.reviewed_at = now or utc_now()
        unit.in_service = False
        await session.flush()
        return fault, unit

    async def dismiss_fault(
        self, session: AsyncSession, fault_id: int, staff_id: UUID
    ) -> EquipmentFault:
        fault = await self._locked_fault(session, fault_id, FaultStatus.REPORTED)
        fault.status = FaultStatus.DISMISSED
        fault.reviewed_by_id = staff_id
        fault.reviewed_at = utc_now()
        await session.flush()
        return fault

    async def resolve_fault(
        self, session: AsyncSession, fault_id: int, staff_id: UUID
    ) -> EquipmentFault:
        """Mark a confirmed fault repaired; the unit returns once it has no other open fault."""
        fault = await self._locked_fault(session, fault_id, FaultStatus.CONFIRMED)
        fault.status = FaultStatus.RESOLVED
        fault.resolved_by_id = staff_id
        fault.resolved_at = utc_now()
        unit = await session.scalar(
            select(EquipmentUnit).where(EquipmentUnit.id == fault.unit_id).with_for_update()
        )
        still_faulty = await session.scalar(
            select(func.count(EquipmentFault.id)).where(
                EquipmentFault.unit_id == unit.id,
                EquipmentFault.status == FaultStatus.CONFIRMED,
                EquipmentFault.id != fault.id,
            )
        )
        if not still_faulty:
            unit.in_service = True
        await session.flush()
        return fault

    async def _locked_fault(
        self, session: AsyncSession, fault_id: int, expected: FaultStatus
    ) -> EquipmentFault:
        fault = await session.scalar(
            select(EquipmentFault).where(EquipmentFault.id == fault_id).with_for_update()
        )
        if fault is None:
            raise AppError("fault was not found", HTTPStatus.NOT_FOUND)
        if fault.status != expected:
            message = f"a {fault.status.value} fault cannot be changed this way"
            raise AppError(message, HTTPStatus.CONFLICT)
        return fault
