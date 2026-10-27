from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.auth import UserRole
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.facilities.service import EquipmentUnitNotFoundError
from app.modules.sessions.dependencies import TimetableServiceDependency
from app.modules.sessions.schemas import (
    CreateSessionRequest,
    GenerateEquipmentSlotsRequest,
    SessionResponse,
)
from app.modules.sessions.service import EquipmentUnavailableError

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    service: TimetableServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> Any:
    """Add a class, pool lane block, personal training or equipment slot to the timetable."""
    try:
        return await service.create(payload)
    except EquipmentUnitNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except EquipmentUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/equipment-slots",
    response_model=list[SessionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def generate_equipment_slots(
    payload: GenerateEquipmentSlotsRequest,
    service: TimetableServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> Any:
    """Generate back-to-back slots on one unit; times it already has a slot are skipped."""
    try:
        return await service.generate_equipment_slots(payload)
    except EquipmentUnitNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except EquipmentUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("", response_model=list[SessionResponse])
async def list_upcoming_sessions(
    _: CurrentUser, service: TimetableServiceDependency
) -> Any:
    """Timetable sessions that have not ended yet, with the places left."""
    return await service.upcoming()
