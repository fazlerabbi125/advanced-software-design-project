from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSessionDep
from app.modules.timetable_sessions.service import TimetableService


def get_timetable_service(session: DbSessionDep) -> TimetableService:
    return TimetableService(session)


TimetableServiceDependency = Annotated[TimetableService, Depends(get_timetable_service)]
