import hashlib
import secrets
from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.models.access import AccessZone
from app.modules.access.access_service import AccessService
from app.modules.access.occupancy import ZoneOccupancy, get_zone_occupancy
from app.modules.access.policies import AccessPolicy, build_policies
from app.modules.access.scanner_service import AuthenticatedScanner, ScannerCheckInService
from app.modules.memberships.dependencies import MembershipServiceDep


def get_zone_occupancy_dependency() -> ZoneOccupancy:
    return get_zone_occupancy()


ZoneOccupancyDep = Annotated[ZoneOccupancy, Depends(get_zone_occupancy_dependency)]


def get_access_policies(
    memberships: MembershipServiceDep, occupancy: ZoneOccupancyDep
) -> Mapping[AccessZone, AccessPolicy]:
    return build_policies(memberships, occupancy, get_settings().vip_room_capacity)


AccessPoliciesDep = Annotated[Mapping[AccessZone, AccessPolicy], Depends(get_access_policies)]


def get_access_service(
    occupancy: ZoneOccupancyDep,
    policies: AccessPoliciesDep,
) -> AccessService:
    return AccessService(occupancy, policies)


def get_authenticated_scanner(
    x_device_key: Annotated[str | None, Header()] = None,
) -> AuthenticatedScanner:
    """Identify the door scanner without retaining its raw secret."""
    if x_device_key:
        for device_key, zone in get_settings().scanner_device_keys.items():
            if secrets.compare_digest(device_key, x_device_key):
                return AuthenticatedScanner(
                    zone=AccessZone(zone),
                    key_fingerprint=hashlib.sha256(x_device_key.encode()).hexdigest(),
                )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown access device")


AccessServiceDep = Annotated[AccessService, Depends(get_access_service)]


def get_scanner_check_in_service(access: AccessServiceDep) -> ScannerCheckInService:
    return ScannerCheckInService(access)


ScannerCheckInServiceDep = Annotated[ScannerCheckInService, Depends(get_scanner_check_in_service)]
AuthenticatedScannerDep = Annotated[AuthenticatedScanner, Depends(get_authenticated_scanner)]
