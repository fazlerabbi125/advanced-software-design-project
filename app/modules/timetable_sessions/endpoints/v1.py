from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import DbSessionDep
from app.models.auth import UserRole
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.facilities.service import EquipmentUnitNotFoundError
from app.modules.timetable_sessions.dependencies import TimetableServiceDependency
from app.modules.timetable_sessions.schemas import (
    CreateSessionRequest,
    GenerateEquipmentSlotsRequest,
    SessionResponse,
)
from app.modules.timetable_sessions.service import EquipmentUnavailableError

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    description="Create a timetable session.",
)
async def create_session(
    payload: CreateSessionRequest,
    session: DbSessionDep,
    service: TimetableServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> Any:
    try:
        timetable_session = await service.create(payload)
        await session.commit()
        return timetable_session
    except EquipmentUnitNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except EquipmentUnavailableError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/equipment-slots",
    response_model=list[SessionResponse],
    status_code=status.HTTP_201_CREATED,
    description="Generate available equipment slots for one unit.",
)
async def generate_equipment_slots(
    payload: GenerateEquipmentSlotsRequest,
    session: DbSessionDep,
    service: TimetableServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> Any:
    try:
        slots = await service.generate_equipment_slots(payload)
        await session.commit()
        return slots
    except EquipmentUnitNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except EquipmentUnavailableError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise


@router.get(
    "", response_model=list[SessionResponse], description="List upcoming timetable sessions."
)
async def list_upcoming_sessions(_: CurrentUser, service: TimetableServiceDependency) -> Any:
    return await service.upcoming()
