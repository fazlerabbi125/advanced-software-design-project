from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.models.facilities import FaultStatus
from app.modules.auth.dependencies import CurrentUser
from app.modules.facilities.dependencies import (
    FacilitiesServiceDependency,
    OutageHandlerDependency,
    StaffUser,
)
from app.modules.facilities.schemas import (
    ConfirmFaultResponse,
    EquipmentUnitResponse,
    FaultResponse,
    RegisterUnitRequest,
    ReportFaultRequest,
)
from app.modules.facilities.service import (
    EquipmentUnitNotFoundError,
    FaultNotFoundError,
    FaultStateError,
    UnitNameTakenError,
)
from app.shared.helpers import utc_now

router = APIRouter(prefix="/equipment", tags=["equipment"])


def not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def conflict(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get("", response_model=list[EquipmentUnitResponse])
async def list_units(
    _: CurrentUser, service: FacilitiesServiceDependency, equipment_type: str | None = None
) -> Any:
    """Registered equipment and whether each unit is in service."""
    return await service.list_units(equipment_type)


@router.post("", response_model=EquipmentUnitResponse, status_code=status.HTTP_201_CREATED)
async def register_unit(
    payload: RegisterUnitRequest, _: StaffUser, service: FacilitiesServiceDependency
) -> Any:
    try:
        return await service.register_unit(payload.name, payload.equipment_type, payload.zone)
    except UnitNameTakenError as error:
        raise conflict(error) from error


@router.post("/{unit_id}/faults", response_model=FaultResponse, status_code=status.HTTP_201_CREATED)
async def report_fault(
    unit_id: int,
    payload: ReportFaultRequest,
    current_user: CurrentUser,
    service: FacilitiesServiceDependency,
) -> Any:
    """Any member or staff member can report a fault; staff then confirm or dismiss it."""
    try:
        return await service.report_fault(unit_id, current_user.id, payload.description)
    except EquipmentUnitNotFoundError as error:
        raise not_found(error) from error


@router.get("/faults", response_model=list[FaultResponse])
async def list_faults(
    _: StaffUser,
    service: FacilitiesServiceDependency,
    fault_status: Annotated[FaultStatus | None, Query(alias="status")] = None,
) -> Any:
    """Faults, newest first; filter with ?status=reported to see what needs reviewing."""
    return await service.list_faults(fault_status)


@router.post("/faults/{fault_id}/confirm", response_model=ConfirmFaultResponse)
async def confirm_fault(
    fault_id: int,
    staff: StaffUser,
    service: FacilitiesServiceDependency,
    outages: OutageHandlerDependency,
) -> Any:
    """Take the unit out of service and move each future slot to a free unit of the same
    type, or cancel its bookings when none is free. Lists every affected member."""
    now = utc_now()
    try:
        fault, unit = await service.confirm_fault(fault_id, staff.id, now)
    except FaultNotFoundError as error:
        raise not_found(error) from error
    except FaultStateError as error:
        raise conflict(error) from error
    outcome = await outages.handle(unit, now)
    await service.save(fault)
    return {
        "fault": fault,
        "moved_slots": outcome.moved,
        "cancelled_bookings": outcome.cancelled,
    }


@router.post("/faults/{fault_id}/dismiss", response_model=FaultResponse)
async def dismiss_fault(
    fault_id: int, staff: StaffUser, service: FacilitiesServiceDependency
) -> Any:
    try:
        return await service.dismiss_fault(fault_id, staff.id)
    except FaultNotFoundError as error:
        raise not_found(error) from error
    except FaultStateError as error:
        raise conflict(error) from error


@router.post("/faults/{fault_id}/resolve", response_model=FaultResponse)
async def resolve_fault(
    fault_id: int, staff: StaffUser, service: FacilitiesServiceDependency
) -> Any:
    """Mark a confirmed fault repaired; the unit returns to service if no other fault is open."""
    try:
        return await service.resolve_fault(fault_id, staff.id)
    except FaultNotFoundError as error:
        raise not_found(error) from error
    except FaultStateError as error:
        raise conflict(error) from error
