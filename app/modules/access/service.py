import logging
from collections.abc import Mapping

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessEvent, AccessLog, AccessZone
from app.modules.access.occupancy import decrement_occupancy, increment_occupancy
from app.modules.access.policies import AccessDeniedError, AccessPolicy, build_policies
from app.modules.memberships.service import MembershipService
from app.utils.helpers import utc_now

logger = logging.getLogger(__name__)


class AccessService:
    def __init__(
        self,
        session: AsyncSession,
        policies: Mapping[AccessZone, AccessPolicy] | None = None,
    ):
        self.session = session
        self.memberships = MembershipService(session)
        self.policies = policies if policies is not None else build_policies(self.memberships)

    async def check_in(
        self,
        member_id: int,
        zone: AccessZone,
        source: str = "biometric",
        event: AccessEvent = AccessEvent.CHECK_IN,
    ) -> AccessLog:
        policy = self.policies.get(zone)
        if policy is None:
            raise AccessDeniedError("no access rule is set up for this zone")
        await policy.check(member_id, zone)

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
