import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.core.dependencies import DbSession
from app.models.access import AccessZone
from app.modules.access.service import AccessService


def get_access_service(session: DbSession) -> AccessService:
    return AccessService(session)


def get_scanner_zone(x_device_key: Annotated[str | None, Header()] = None) -> AccessZone:
    """Identify the door scanner by its secret key and return the zone its door opens."""
    if x_device_key:
        for device_key, zone in get_settings().scanner_device_keys.items():
            if secrets.compare_digest(device_key, x_device_key):
                return AccessZone(zone)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown access device")


AccessServiceDependency = Annotated[AccessService, Depends(get_access_service)]
ScannerZone = Annotated[AccessZone, Depends(get_scanner_zone)]
