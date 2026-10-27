import logging
from collections.abc import Mapping

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.access import AccessEvent, AccessLog, AccessZone
from app.models.auth import User
from app.modules.access.occupancy import ZoneOccupancy, get_zone_occupancy
from app.modules.access.policies import AccessDeniedError, AccessPolicy, build_policies
from app.modules.memberships.service import MembershipService
from app.utils.helpers import utc_now

logger = logging.getLogger(__name__)


class AccessService:
    def __init__(
        self,
        session: AsyncSession,
        policies: Mapping[AccessZone, AccessPolicy] | None = None,
        occupancy: ZoneOccupancy | None = None,
    ):
        self.session = session
        self.memberships = MembershipService(session)
        self.occupancy = occupancy if occupancy is not None else get_zone_occupancy()
        self.policies = (
            policies
            if policies is not None
            else build_policies(self.memberships, self.occupancy, get_settings().vip_room_capacity)
        )

    async def check_in(
        self,
        member_id: int,
        zone: AccessZone,
        source: str = "biometric",
        event: AccessEvent = AccessEvent.CHECK_IN,
        staff_id: int | None = None,
        reason: str | None = None,
    ) -> AccessLog:
        if event == AccessEvent.MANUAL_CHECK_IN and (staff_id is None or not reason):
            raise ValueError("a manual check-in must record the staff member and a reason")
        # Scanner and staff check-ins name the member directly, so the account itself must be
        # checked here; a disabled account is refused even if its membership is still active.
        member = await self.session.get(User, member_id)
        if member is None or not member.is_active:
            raise AccessDeniedError("this member account is not active")
        policy = self.policies.get(zone)
        if policy is None:
            raise AccessDeniedError("no access rule is set up for this zone")
        # On success the policy has already counted the member in the zone.
        took_new_place = await policy.check(member_id, zone)

        access_log = AccessLog(
            member_id=member_id,
            event=event,
            zone=zone.value,
            source=source,
            occurred_at=utc_now(),
            performed_by_staff_id=staff_id,
            staff_reason=reason,
        )
        self.session.add(access_log)
        try:
            await self.session.commit()
        except Exception:
            # The entry was not recorded, so give back a place this check-in took. A member
            # who was already inside keeps the place their earlier check-in gave them.
            if took_new_place:
                await self.release_place(member_id, zone)
            raise
        await self.session.refresh(access_log)
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
        await self.release_place(member_id, zone)
        return access_log

    async def release_place(self, member_id: int, zone: AccessZone) -> None:
        try:
            await self.occupancy.leave(zone.value, member_id)
        except RedisError:
            logger.exception("Unable to update occupancy for zone %s", zone.value)

    async def waitlist_position(self, member_id: int, zone: AccessZone) -> int | None:
        return await self.occupancy.waitlist_position(zone.value, member_id)

    async def leave_waitlist(self, member_id: int, zone: AccessZone) -> None:
        await self.occupancy.leave_waitlist(zone.value, member_id)

    async def current_occupancy(self) -> dict[str, int]:
        return {zone.value: await self.occupancy.count(zone.value) for zone in AccessZone}

    async def list_member_access(self, member_id: int) -> list[AccessLog]:
        result = await self.session.scalars(
            select(AccessLog)
            .where(AccessLog.member_id == member_id)
            .order_by(AccessLog.occurred_at.desc())
        )
        return list(result)
