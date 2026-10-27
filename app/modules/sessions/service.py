from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.timetable_sessions import TimetableSession
from app.modules.sessions.schemas import CreateSessionRequest
from app.shared.helpers import utc_now


class TimetableService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: CreateSessionRequest) -> TimetableSession:
        timetable_session = TimetableSession(
            resource_name=payload.resource_name.strip(),
            resource_type=payload.resource_type,
            starts_at=payload.starts_at.astimezone(UTC),
            ends_at=payload.ends_at.astimezone(UTC),
            capacity=payload.capacity,
            allocated_count=0,
            station_count=payload.station_count,
        )
        self.session.add(timetable_session)
        await self.session.commit()
        await self.session.refresh(timetable_session)
        return timetable_session

    async def upcoming(self, after: datetime | None = None) -> list[TimetableSession]:
        """Sessions that have not ended yet, soonest first."""
        statement = (
            select(TimetableSession)
            .where(TimetableSession.ends_at > (after or utc_now()))
            .order_by(TimetableSession.starts_at, TimetableSession.id)
        )
        return list((await self.session.scalars(statement)).all())
