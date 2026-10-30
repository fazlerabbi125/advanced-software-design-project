import logging
from http import HTTPStatus
from typing import Protocol
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.access import AccessZone
from app.models.memberships import MembershipEntitlement
from app.modules.access.occupancy import EntryOutcome, ZoneOccupancy
from app.modules.memberships.service import MembershipService
from app.shared.constants import SECONDS_PER_MINUTE, ZONE_STAY_MINUTES

logger = logging.getLogger(__name__)


class AccessPolicy(Protocol):
    """A rule that decides whether a member may enter a zone."""

    async def check(self, session: AsyncSession, member_id: UUID, zone: AccessZone) -> bool:
        """Admit the member, or raise AppError to refuse entry.

        Returning normally means the member is let in and counted in the zone. Returns
        True when this call took a new place, so the caller knows to give it back if
        the entry cannot be recorded; False when the member already held one.
        """
        ...


def stay_seconds(zone: AccessZone) -> int:
    return ZONE_STAY_MINUTES[zone.value] * SECONDS_PER_MINUTE


class GymFloorPolicy:
    """Members whose plan includes the gym floor may enter. There is no capacity limit."""

    def __init__(self, memberships: MembershipService, occupancy: ZoneOccupancy) -> None:
        self.memberships = memberships
        self.occupancy = occupancy

    async def check(self, session: AsyncSession, member_id: UUID, zone: AccessZone) -> bool:
        if not await self.memberships.has_entitlement(
            session, member_id, MembershipEntitlement.GYM_FLOOR_ACCESS
        ):
            raise AppError(
                "your membership plan does not allow access to this zone", HTTPStatus.FORBIDDEN
            )
        try:
            entry = await self.occupancy.enter(zone.value, member_id, stay_seconds(zone))
        except RedisError:
            # The gym floor count is for information only, so entry still goes ahead.
            logger.exception("Unable to count entry to zone %s", zone.value)
            return False
        return entry.outcome == EntryOutcome.ADMITTED


class VipAreaPolicy:
    """Members whose plan includes the VIP area may enter a VIP room while it has space.

    When the room is full the member joins its waiting list instead.
    """

    def __init__(
        self, memberships: MembershipService, occupancy: ZoneOccupancy, capacity: int
    ) -> None:
        self.memberships = memberships
        self.occupancy = occupancy
        self.capacity = capacity

    async def check(self, session: AsyncSession, member_id: UUID, zone: AccessZone) -> bool:
        if not await self.memberships.has_entitlement(
            session, member_id, MembershipEntitlement.VIP_AREA_ACCESS
        ):
            raise AppError(
                "your membership plan does not allow access to this zone", HTTPStatus.FORBIDDEN
            )
        try:
            entry = await self.occupancy.enter(
                zone.value, member_id, stay_seconds(zone), self.capacity
            )
        except RedisError as error:
            # Without the count we cannot keep to the limit, so the room stays closed.
            logger.exception("Unable to check capacity for zone %s", zone.value)
            raise AppError(
                "VIP entry is unavailable right now, please ask a member of staff",
                HTTPStatus.FORBIDDEN,
            ) from error
        if entry.outcome == EntryOutcome.WAITLISTED:
            room = zone.value.removeprefix("vip_").replace("_", " ")
            raise AppError(
                f"the {room} is full, you are number "
                f"{entry.waitlist_position or 1} on the waiting list",
                HTTPStatus.CONFLICT,
            )
        return entry.outcome == EntryOutcome.ADMITTED


def build_policies(
    memberships: MembershipService, occupancy: ZoneOccupancy, vip_room_capacity: int
) -> dict[AccessZone, AccessPolicy]:
    gym_floor = GymFloorPolicy(memberships, occupancy)
    vip_area = VipAreaPolicy(memberships, occupancy, vip_room_capacity)
    return {
        AccessZone.GYM_FLOOR: gym_floor,
        AccessZone.VIP_SAUNA: vip_area,
        AccessZone.VIP_MASSAGE: vip_area,
        AccessZone.VIP_COLD_PLUNGE: vip_area,
    }
