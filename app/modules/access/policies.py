from typing import Protocol

from app.models.access import AccessZone
from app.models.memberships import MembershipEntitlement
from app.modules.memberships.service import MembershipService


class AccessDeniedError(ValueError):
    """Raised when a member is not allowed into a zone."""


class AccessPolicy(Protocol):
    """A rule that decides whether a member may enter a zone."""

    async def check(self, member_id: int, zone: AccessZone) -> None:
        """Return normally to allow entry, or raise AccessDeniedError to refuse it."""
        ...


class GymFloorPolicy:
    def __init__(self, memberships: MembershipService) -> None:
        self.memberships = memberships

    async def check(self, member_id: int, zone: AccessZone) -> None:
        if not await self.memberships.has_entitlement(
            member_id, MembershipEntitlement.GYM_FLOOR_ACCESS
        ):
            raise AccessDeniedError("your membership plan does not allow access to this zone")


class VipAreaPolicy:
    def __init__(self, memberships: MembershipService) -> None:
        self.memberships = memberships

    async def check(self, member_id: int, zone: AccessZone) -> None:
        if not await self.memberships.has_entitlement(
            member_id, MembershipEntitlement.VIP_AREA_ACCESS
        ):
            raise AccessDeniedError("your membership plan does not allow access to this zone")


def build_policies(memberships: MembershipService) -> dict[AccessZone, AccessPolicy]:
    gym_floor = GymFloorPolicy(memberships)
    vip_area = VipAreaPolicy(memberships)
    return {
        AccessZone.GYM_FLOOR: gym_floor,
        AccessZone.VIP_SAUNA: vip_area,
        AccessZone.VIP_MASSAGE: vip_area,
        AccessZone.VIP_COLD_PLUNGE: vip_area,
    }
