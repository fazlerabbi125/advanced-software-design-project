from typing import Annotated

from fastapi import Depends

from app.modules.timetable_sessions.service import TimetableService


def get_timetable_service() -> TimetableService:
    return TimetableService()


TimetableServiceDependency = Annotated[TimetableService, Depends(get_timetable_service)]
