import logging
from asyncio import gather
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessEvent, AccessLog, AccessZone
from app.models.auth import User
from app.modules.access.occupancy import ZoneOccupancy
from app.modules.access.policies import AccessDeniedError, AccessPolicy
from app.modules.memberships.service import MembershipService
from app.shared.helpers import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckInResult:
    access_log: AccessLog
    took_new_place: bool


class AccessService:
    def __init__(
        self,
        session: AsyncSession,
        memberships: MembershipService,
        occupancy: ZoneOccupancy,
        policies: Mapping[AccessZone, AccessPolicy],
    ):
        self.session = session
        self.memberships = memberships
        self.occupancy = occupancy
        self.policies = policies

    async def check_in(
        self,
        member_id: UUID,
        zone: AccessZone,
        source: str = "biometric",
        event: AccessEvent = AccessEvent.CHECK_IN,
        staff_id: UUID | None = None,
        reason: str | None = None,
    ) -> CheckInResult:
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
        return CheckInResult(access_log=access_log, took_new_place=took_new_place)

    async def check_out(self, member_id: UUID, zone: AccessZone) -> AccessLog:
        access_log = AccessLog(
            member_id=member_id,
            event=AccessEvent.CHECK_OUT,
            zone=zone.value,
            occurred_at=utc_now(),
        )
        self.session.add(access_log)
        return access_log

    async def release_place(self, member_id: UUID, zone: AccessZone) -> None:
        try:
            await self.occupancy.leave(zone.value, member_id)
        except RedisError:
            logger.exception("Unable to update occupancy for zone %s", zone.value)

    async def waitlist_position(self, member_id: UUID, zone: AccessZone) -> int | None:
        return await self.occupancy.waitlist_position(zone.value, member_id)

    async def leave_waitlist(self, member_id: UUID, zone: AccessZone) -> None:
        await self.occupancy.leave_waitlist(zone.value, member_id)

    async def current_occupancy(self) -> dict[str, int]:
        zones = tuple(AccessZone)
        counts = await gather(*(self.occupancy.count(zone.value) for zone in zones))
        return dict(zip((zone.value for zone in zones), counts, strict=True))

    async def list_member_access(self, member_id: UUID) -> list[AccessLog]:
        result = await self.session.scalars(
            select(AccessLog)
            .where(AccessLog.member_id == member_id)
            .order_by(AccessLog.occurred_at.desc())
        )
        return list(result)
