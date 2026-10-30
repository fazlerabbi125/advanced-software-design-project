from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.core.dependencies import DbSessionDep
from app.core.exceptions import AppError, http_error
from app.models.facilities import FaultStatus
from app.modules.auth.dependencies import CurrentUser
from app.modules.facilities.dependencies import (
    FacilitiesServiceDep,
    OutageHandlerDep,
    StaffUser,
)
from app.modules.facilities.schemas import (
    ConfirmFaultResponse,
    EquipmentUnitResponse,
    FaultResponse,
    RegisterUnitRequest,
    ReportFaultRequest,
)
from app.shared.helpers import utc_now
from app.shared.pagination import PageParamsDep, PageResponse

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get(
    "", response_model=PageResponse[EquipmentUnitResponse], description="List equipment units."
)
async def list_units(
    _: CurrentUser,
    session: DbSessionDep,
    service: FacilitiesServiceDep,
    params: PageParamsDep,
    equipment_type: str | None = None,
) -> Any:
    result = await service.list_units(session, params, equipment_type)
    return {"items": result.items, "meta": result.meta}


@router.post(
    "",
    response_model=EquipmentUnitResponse,
    status_code=status.HTTP_201_CREATED,
    description="Register an equipment unit.",
)
async def register_unit(
    payload: RegisterUnitRequest,
    _: StaffUser,
    session: DbSessionDep,
    service: FacilitiesServiceDep,
) -> Any:
    try:
        unit = await service.register_unit(
            session, payload.name, payload.equipment_type, payload.zone
        )
        await session.commit()
        return unit
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/{unit_id}/faults",
    response_model=FaultResponse,
    status_code=status.HTTP_201_CREATED,
    description="Report an equipment fault.",
)
async def report_fault(
    unit_id: int,
    payload: ReportFaultRequest,
    current_user: CurrentUser,
    session: DbSessionDep,
    service: FacilitiesServiceDep,
) -> Any:
    try:
        fault = await service.report_fault(session, unit_id, current_user.id, payload.description)
        await session.commit()
        return fault
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise


@router.get(
    "/faults",
    response_model=PageResponse[FaultResponse],
    description="List reported equipment faults.",
)
async def list_faults(
    _: StaffUser,
    session: DbSessionDep,
    service: FacilitiesServiceDep,
    params: PageParamsDep,
    fault_status: Annotated[FaultStatus | None, Query(alias="status")] = None,
) -> Any:
    result = await service.list_faults(session, params, fault_status)
    return {"items": result.items, "meta": result.meta}


@router.post(
    "/faults/{fault_id}/confirm",
    response_model=ConfirmFaultResponse,
    description="Confirm a fault and handle affected slots.",
)
async def confirm_fault(
    fault_id: int,
    staff: StaffUser,
    session: DbSessionDep,
    service: FacilitiesServiceDep,
    outages: OutageHandlerDep,
) -> Any:
    now = utc_now()
    try:
        fault, unit = await service.confirm_fault(session, fault_id, staff.id, now)
        outcome = await outages.handle(session, unit, now)
        await session.commit()
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise
    return {
        "fault": fault,
        "moved_slots": outcome.moved,
        "cancelled_bookings": outcome.cancelled,
    }


@router.post(
    "/faults/{fault_id}/dismiss",
    response_model=FaultResponse,
    description="Dismiss a reported equipment fault.",
)
async def dismiss_fault(
    fault_id: int, staff: StaffUser, session: DbSessionDep, service: FacilitiesServiceDep
) -> Any:
    try:
        fault = await service.dismiss_fault(session, fault_id, staff.id)
        await session.commit()
        return fault
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/faults/{fault_id}/resolve",
    response_model=FaultResponse,
    description="Resolve a confirmed equipment fault.",
)
async def resolve_fault(
    fault_id: int, staff: StaffUser, session: DbSessionDep, service: FacilitiesServiceDep
) -> Any:
    try:
        fault = await service.resolve_fault(session, fault_id, staff.id)
        await session.commit()
        return fault
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise
