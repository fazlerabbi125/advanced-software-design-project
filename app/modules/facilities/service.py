"""Equipment units and the fault workflow: reported, then confirmed or dismissed, then resolved.

The service never touches bookings. Confirming a fault takes the unit out of service and
leaves the transaction open, so the caller can move or cancel the unit's future slots
(bookings module) and commit both together.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.facilities import EquipmentFault, EquipmentUnit, FaultStatus
from app.shared.helpers import utc_now


class EquipmentUnitNotFoundError(LookupError):
    pass


class FaultNotFoundError(LookupError):
    pass


class FaultStateError(ValueError):
    pass


class UnitNameTakenError(ValueError):
    pass


def normalise_equipment_type(value: str) -> str:
    """'Squat rack' and 'squat_rack' name the same type."""
    return "_".join(value.strip().lower().split())


class FacilitiesService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_unit(self, name: str, equipment_type: str, zone: str) -> EquipmentUnit:
        name = name.strip()
        taken = await self.session.scalar(
            select(EquipmentUnit.id).where(func.lower(EquipmentUnit.name) == name.lower())
        )
        if taken is not None:
            raise UnitNameTakenError(f"a unit called {name!r} already exists")
        unit = EquipmentUnit(
            name=name, equipment_type=normalise_equipment_type(equipment_type), zone=zone
        )
        self.session.add(unit)
        try:
            await self.session.commit()
        except IntegrityError as error:
            # Another request registered the same name between the check and the insert.
            await self.session.rollback()
            raise UnitNameTakenError(f"a unit called {name!r} already exists") from error
        await self.session.refresh(unit)
        return unit

    async def list_units(self, equipment_type: str | None = None) -> list[EquipmentUnit]:
        statement = select(EquipmentUnit).order_by(EquipmentUnit.equipment_type, EquipmentUnit.name)
        if equipment_type is not None:
            statement = statement.where(
                EquipmentUnit.equipment_type == normalise_equipment_type(equipment_type)
            )
        return list((await self.session.scalars(statement)).all())

    async def get_unit(self, unit_id: int) -> EquipmentUnit:
        unit = await self.session.get(EquipmentUnit, unit_id)
        if unit is None:
            raise EquipmentUnitNotFoundError("equipment unit was not found")
        return unit

    async def report_fault(
        self, unit_id: int, reporter_id: UUID, description: str
    ) -> EquipmentFault:
        await self.get_unit(unit_id)
        fault = EquipmentFault(
            unit_id=unit_id,
            reported_by_id=reporter_id,
            description=description.strip(),
            status=FaultStatus.REPORTED,
        )
        self.session.add(fault)
        await self.session.commit()
        await self.session.refresh(fault)
        return fault

    async def list_faults(self, status: FaultStatus | None = None) -> list[EquipmentFault]:
        statement = select(EquipmentFault).order_by(EquipmentFault.created_at.desc())
        if status is not None:
            statement = statement.where(EquipmentFault.status == status)
        return list((await self.session.scalars(statement)).all())

    async def confirm_fault(
        self, fault_id: int, staff_id: UUID, now: datetime | None = None
    ) -> tuple[EquipmentFault, EquipmentUnit]:
        """Confirm a reported fault and take its unit out of service. Does not commit.

        Every unit of the same type is locked first, in id order, so two faults confirmed
        at once cannot move slots onto the same unit or deadlock on each other.
        """
        fault = await self._locked_fault(fault_id, FaultStatus.REPORTED)
        unit = await self.session.get(EquipmentUnit, fault.unit_id)
        await self.session.execute(
            select(EquipmentUnit.id)
            .where(EquipmentUnit.equipment_type == unit.equipment_type)
            .order_by(EquipmentUnit.id)
            .with_for_update()
        )
        await self.session.refresh(unit)
        fault.status = FaultStatus.CONFIRMED
        fault.reviewed_by_id = staff_id
        fault.reviewed_at = now or utc_now()
        unit.in_service = False
        await self.session.flush()
        return fault, unit

    async def save(self, fault: EquipmentFault) -> None:
        """Commit a confirmation once the unit's slots have been dealt with."""
        await self.session.commit()
        await self.session.refresh(fault)

    async def dismiss_fault(self, fault_id: int, staff_id: UUID) -> EquipmentFault:
        fault = await self._locked_fault(fault_id, FaultStatus.REPORTED)
        fault.status = FaultStatus.DISMISSED
        fault.reviewed_by_id = staff_id
        fault.reviewed_at = utc_now()
        await self.session.commit()
        await self.session.refresh(fault)
        return fault

    async def resolve_fault(self, fault_id: int, staff_id: UUID) -> EquipmentFault:
        """Mark a confirmed fault repaired; the unit returns once it has no other open fault."""
        fault = await self._locked_fault(fault_id, FaultStatus.CONFIRMED)
        fault.status = FaultStatus.RESOLVED
        fault.resolved_by_id = staff_id
        fault.resolved_at = utc_now()
        unit = await self.session.scalar(
            select(EquipmentUnit).where(EquipmentUnit.id == fault.unit_id).with_for_update()
        )
        still_faulty = await self.session.scalar(
            select(func.count(EquipmentFault.id)).where(
                EquipmentFault.unit_id == unit.id,
                EquipmentFault.status == FaultStatus.CONFIRMED,
                EquipmentFault.id != fault.id,
            )
        )
        if not still_faulty:
            unit.in_service = True
        await self.session.commit()
        await self.session.refresh(fault)
        return fault

    async def _locked_fault(self, fault_id: int, expected: FaultStatus) -> EquipmentFault:
        fault = await self.session.scalar(
            select(EquipmentFault).where(EquipmentFault.id == fault_id).with_for_update()
        )
        if fault is None:
            await self.session.rollback()
            raise FaultNotFoundError("fault was not found")
        if fault.status != expected:
            message = f"a {fault.status.value} fault cannot be changed this way"
            await self.session.rollback()
            raise FaultStateError(message)
        return fault
