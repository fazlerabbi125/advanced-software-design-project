import secrets
from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.core.dependencies import DbSessionDep
from app.models.access import AccessZone
from app.modules.access.occupancy import ZoneOccupancy, get_zone_occupancy
from app.modules.access.policies import AccessPolicy, build_policies
from app.modules.access.service import AccessService
from app.modules.memberships.dependencies import MembershipServiceDependency


def get_zone_occupancy_dependency() -> ZoneOccupancy:
    return get_zone_occupancy()


ZoneOccupancyDependency = Annotated[ZoneOccupancy, Depends(get_zone_occupancy_dependency)]


def get_access_policies(
    memberships: MembershipServiceDependency, occupancy: ZoneOccupancyDependency
) -> Mapping[AccessZone, AccessPolicy]:
    return build_policies(memberships, occupancy, get_settings().vip_room_capacity)


AccessPoliciesDependency = Annotated[
    Mapping[AccessZone, AccessPolicy], Depends(get_access_policies)
]


def get_access_service(
    session: DbSessionDep,
    memberships: MembershipServiceDependency,
    occupancy: ZoneOccupancyDependency,
    policies: AccessPoliciesDependency,
) -> AccessService:
    return AccessService(session, memberships, occupancy, policies)


def get_scanner_zone(x_device_key: Annotated[str | None, Header()] = None) -> AccessZone:
    """Identify the door scanner by its secret key and return the zone its door opens."""
    if x_device_key:
        for device_key, zone in get_settings().scanner_device_keys.items():
            if secrets.compare_digest(device_key, x_device_key):
                return AccessZone(zone)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown access device")


AccessServiceDependency = Annotated[AccessService, Depends(get_access_service)]
ScannerZone = Annotated[AccessZone, Depends(get_scanner_zone)]
