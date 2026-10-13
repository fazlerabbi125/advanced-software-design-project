import logging

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessEvent, AccessLog, AccessZone
from app.models.memberships import MembershipEntitlement
from app.modules.access.occupancy import decrement_occupancy, increment_occupancy
from app.modules.memberships.service import MembershipService
from app.utils.helpers import utc_now

logger = logging.getLogger(__name__)


class AccessService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.memberships = MembershipService(session)

    async def check_in(
        self,
        member_id: int,
        zone: AccessZone,
        source: str = "biometric",
        event: AccessEvent = AccessEvent.CHECK_IN,
    ) -> AccessLog:
        required_entitlement = (
            MembershipEntitlement.GYM_FLOOR_ACCESS
            if zone == AccessZone.GYM_FLOOR
            else MembershipEntitlement.VIP_AREA_ACCESS
        )
        if not await self.memberships.has_entitlement(member_id, required_entitlement):
            raise ValueError("your membership plan does not allow access to this zone")

        access_log = AccessLog(
            member_id=member_id,
            event=event,
            zone=zone.value,
            source=source,
            occurred_at=utc_now(),
        )
        self.session.add(access_log)
        await self.session.commit()
        await self.session.refresh(access_log)
        try:
            await increment_occupancy(zone.value)
        except RedisError:
            logger.exception("Unable to increment occupancy for zone %s", zone.value)
        return access_log

    async def check_out(self, member_id: int, zone: AccessZone) -> AccessLog:
        access_log = AccessLog(
            member_id=member_id,
            event=AccessEvent.CHECK_OUT,
            zone=zone.value,
            occurred_at=utc_now(),
        )
        self.session.add(access_log)
        await self.session.commit()
        await self.session.refresh(access_log)
        try:
            await decrement_occupancy(zone.value)
        except RedisError:
            logger.exception("Unable to decrement occupancy for zone %s", zone.value)
        return access_log

    async def list_member_access(self, member_id: int) -> list[AccessLog]:
        result = await self.session.scalars(
            select(AccessLog)
            .where(AccessLog.member_id == member_id)
            .order_by(AccessLog.occurred_at.desc())
        )
        return list(result)
