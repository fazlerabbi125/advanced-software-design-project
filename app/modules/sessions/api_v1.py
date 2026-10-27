from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.models.auth import UserRole
from app.models.timetable_sessions import TimetableSession
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.sessions.dependencies import TimetableServiceDependency
from app.modules.sessions.schemas import CreateSessionRequest, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


def session_response(timetable_session: TimetableSession) -> SessionResponse:
    return SessionResponse(
        id=timetable_session.id,
        resource_name=timetable_session.resource_name,
        resource_type=timetable_session.resource_type,
        starts_at=timetable_session.starts_at,
        ends_at=timetable_session.ends_at,
        capacity=timetable_session.capacity,
        allocated_count=timetable_session.allocated_count,
        spots_left=timetable_session.spots_left,
        station_count=timetable_session.station_count,
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    service: TimetableServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> SessionResponse:
    """Add a class, pool lane block or personal training slot to the timetable."""
    return session_response(await service.create(payload))


@router.get("", response_model=list[SessionResponse])
async def list_upcoming_sessions(
    _: CurrentUser, service: TimetableServiceDependency
) -> list[SessionResponse]:
    """Timetable sessions that have not ended yet, with the places left."""
    return [session_response(item) for item in await service.upcoming()]
