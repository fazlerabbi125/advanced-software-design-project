from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.models.auth import UserRole
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.sessions.dependencies import TimetableServiceDependency
from app.modules.sessions.schemas import CreateSessionRequest, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    service: TimetableServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> Any:
    """Add a class, pool lane block or personal training slot to the timetable."""
    return await service.create(payload)


@router.get("", response_model=list[SessionResponse])
async def list_upcoming_sessions(
    _: CurrentUser, service: TimetableServiceDependency
) -> Any:
    """Timetable sessions that have not ended yet, with the places left."""
    return await service.upcoming()
