import logging
from typing import Protocol

from redis.exceptions import RedisError

from app.models.access import AccessZone
from app.models.memberships import MembershipEntitlement
from app.modules.access.occupancy import EntryOutcome, ZoneOccupancy
from app.modules.memberships.service import MembershipService
from app.utils.constants import ZONE_STAY_MINUTES

logger = logging.getLogger(__name__)


class AccessDeniedError(ValueError):
    """Raised when a member is not allowed into a zone."""


class ZoneFullError(AccessDeniedError):
    """Raised when a zone has no free places left."""


class AccessPolicy(Protocol):
    """A rule that decides whether a member may enter a zone."""

    async def check(self, member_id: int, zone: AccessZone) -> bool:
        """Admit the member, or raise AccessDeniedError to refuse entry.

        Returning normally means the member is let in and counted in the zone. Returns
        True when this call took a new place, so the caller knows to give it back if
        the entry cannot be recorded; False when the member already held one.
        """
        ...


def stay_seconds(zone: AccessZone) -> int:
    return ZONE_STAY_MINUTES[zone.value] * 60


class GymFloorPolicy:
    """Members whose plan includes the gym floor may enter. There is no capacity limit."""

    def __init__(self, memberships: MembershipService, occupancy: ZoneOccupancy) -> None:
        self.memberships = memberships
        self.occupancy = occupancy

    async def check(self, member_id: int, zone: AccessZone) -> bool:
        if not await self.memberships.has_entitlement(
            member_id, MembershipEntitlement.GYM_FLOOR_ACCESS
        ):
            raise AccessDeniedError("your membership plan does not allow access to this zone")
        try:
            outcome = await self.occupancy.enter(zone.value, member_id, stay_seconds(zone))
        except RedisError:
            # The gym floor count is for information only, so entry still goes ahead.
            logger.exception("Unable to count entry to zone %s", zone.value)
            return False
        return outcome == EntryOutcome.ADMITTED


class VipAreaPolicy:
    """Members whose plan includes the VIP area may enter a VIP room while it has space."""

    def __init__(
        self, memberships: MembershipService, occupancy: ZoneOccupancy, capacity: int
    ) -> None:
        self.memberships = memberships
        self.occupancy = occupancy
        self.capacity = capacity

    async def check(self, member_id: int, zone: AccessZone) -> bool:
        if not await self.memberships.has_entitlement(
            member_id, MembershipEntitlement.VIP_AREA_ACCESS
        ):
            raise AccessDeniedError("your membership plan does not allow access to this zone")
        try:
            outcome = await self.occupancy.enter(
                zone.value, member_id, stay_seconds(zone), self.capacity
            )
        except RedisError as error:
            # Without the count we cannot keep to the limit, so the room stays closed.
            logger.exception("Unable to check capacity for zone %s", zone.value)
            raise AccessDeniedError(
                "VIP entry is unavailable right now, please ask a member of staff"
            ) from error
        if outcome == EntryOutcome.FULL:
            room = zone.value.removeprefix("vip_").replace("_", " ")
            raise ZoneFullError(f"the {room} is full, please try again shortly")
        return outcome == EntryOutcome.ADMITTED


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
