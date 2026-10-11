from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.occupancy import decrement_occupancy, increment_occupancy
from app.domains.memberships.service import MembershipService
from app.models.access import AccessEvent, AccessLog
from app.utils.helpers import utc_now


class AccessService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.memberships = MembershipService(session)

    async def check_in(
        self,
        member_id: int,
        zone: str,
        source: str = "biometric",
        event: AccessEvent = AccessEvent.CHECK_IN,
    ) -> AccessLog:
        if not await self.memberships.has_active_membership(member_id):
            raise ValueError("An active membership is required for access")

        access_log = AccessLog(
            member_id=member_id,
            event=event,
            zone=zone,
            source=source,
            occurred_at=utc_now(),
        )
        self.session.add(access_log)
        await self.session.commit()
        await self.session.refresh(access_log)
        await increment_occupancy(zone)
        return access_log

    async def check_out(self, member_id: int, zone: str) -> AccessLog:
        access_log = AccessLog(
            member_id=member_id,
            event=AccessEvent.CHECK_OUT,
            zone=zone,
            occurred_at=utc_now(),
        )
        self.session.add(access_log)
        await self.session.commit()
        await self.session.refresh(access_log)
        await decrement_occupancy(zone)
        return access_log

    async def list_member_access(self, member_id: int) -> list[AccessLog]:
        result = await self.session.scalars(
            select(AccessLog)
            .where(AccessLog.member_id == member_id)
            .order_by(AccessLog.occurred_at.desc())
        )
        return list(result)
