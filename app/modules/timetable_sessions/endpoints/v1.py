from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DbSessionDep
from app.core.exceptions import AppError, http_error
from app.models.auth import UserRole
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.timetable_sessions.dependencies import TimetableServiceDependency
from app.modules.timetable_sessions.schemas import (
    CreateSessionRequest,
    GenerateEquipmentSlotsRequest,
    SessionResponse,
)

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
        timetable_session = await service.create(session, payload)
        await session.commit()
        return timetable_session
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
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
        slots = await service.generate_equipment_slots(session, payload)
        await session.commit()
        return slots
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise


@router.get(
    "", response_model=list[SessionResponse], description="List upcoming timetable sessions."
)
async def list_upcoming_sessions(
    _: CurrentUser, session: DbSessionDep, service: TimetableServiceDependency
) -> Any:
    return await service.upcoming(session)
