from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.access import AccessEvent, AccessZone
from app.models.auth import UserRole
from app.modules.access.dependencies import AccessServiceDependency, ScannerZone
from app.modules.access.policies import ZoneFullError
from app.modules.access.schemas import (
    AccessLogResponse,
    CheckInRequest,
    DeviceCheckInRequest,
    WaitlistPositionResponse,
)
from app.modules.auth.dependencies import CurrentUser, require_roles

router = APIRouter(prefix="/access", tags=["access"])


@router.post("/check-in", status_code=status.HTTP_201_CREATED)
async def check_in(
    payload: CheckInRequest,
    service: AccessServiceDependency,
    current_user: CurrentUser,
) -> AccessLogResponse:
    member_id = payload.member_id or current_user.id
    if member_id != current_user.id and current_user.role not in {UserRole.STAFF, UserRole.MANAGER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    try:
        access_log = await service.check_in(member_id, payload.zone)
    except ZoneFullError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return AccessLogResponse(
        id=access_log.id,
        member_id=access_log.member_id,
        event=access_log.event.value,
        zone=access_log.zone,
        source=access_log.source,
        occurred_at=access_log.occurred_at,
    )


@router.post(
    "/manual-check-in", response_model=AccessLogResponse, status_code=status.HTTP_201_CREATED
)
async def manual_check_in(
    payload: CheckInRequest,
    service: AccessServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> AccessLogResponse:
    if payload.member_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="member_id is required"
        )
    try:
        access_log = await service.check_in(
            payload.member_id,
            payload.zone,
            source="manual",
            event=AccessEvent.MANUAL_CHECK_IN,
        )
    except ZoneFullError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return AccessLogResponse(
        id=access_log.id,
        member_id=access_log.member_id,
        event=access_log.event.value,
        zone=access_log.zone,
        source=access_log.source,
        occurred_at=access_log.occurred_at,
    )


@router.post("/check-out", response_model=AccessLogResponse, status_code=status.HTTP_201_CREATED)
async def check_out(
    payload: CheckInRequest,
    service: AccessServiceDependency,
    current_user: CurrentUser,
) -> AccessLogResponse:
    member_id = payload.member_id or current_user.id
    if member_id != current_user.id and current_user.role not in {UserRole.STAFF, UserRole.MANAGER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    access_log = await service.check_out(member_id, payload.zone)
    return AccessLogResponse(
        id=access_log.id,
        member_id=access_log.member_id,
        event=access_log.event.value,
        zone=access_log.zone,
        source=access_log.source,
        occurred_at=access_log.occurred_at,
    )


@router.get("/occupancy", response_model=dict[str, int])
async def current_occupancy(
    service: AccessServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> dict[str, int]:
    """Number of people currently inside each zone (staff and managers only)."""
    return await service.current_occupancy()


@router.post(
    "/device-check-in", response_model=AccessLogResponse, status_code=status.HTTP_201_CREATED
)
async def device_check_in(
    payload: DeviceCheckInRequest,
    service: AccessServiceDependency,
    zone: ScannerZone,
) -> AccessLogResponse:
    """Called by a face-recognition door scanner after it has recognised a member.

    The scanner identifies itself with its secret key in the X-Device-Key header; the
    zone comes from the scanner, so a door can only let people into its own room.
    """
    try:
        access_log = await service.check_in(payload.member_id, zone, source="face_recognition")
    except ZoneFullError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return AccessLogResponse(
        id=access_log.id,
        member_id=access_log.member_id,
        event=access_log.event.value,
        zone=access_log.zone,
        source=access_log.source,
        occurred_at=access_log.occurred_at,
    )


@router.get("/waitlist/{zone}", response_model=WaitlistPositionResponse)
async def my_waitlist_position(
    zone: AccessZone,
    service: AccessServiceDependency,
    current_user: CurrentUser,
) -> WaitlistPositionResponse:
    """The signed-in member's place on a room's waiting list (null when not on it)."""
    position = await service.waitlist_position(current_user.id, zone)
    return WaitlistPositionResponse(zone=zone, position=position)


@router.delete("/waitlist/{zone}", status_code=status.HTTP_204_NO_CONTENT)
async def leave_waitlist(
    zone: AccessZone,
    service: AccessServiceDependency,
    current_user: CurrentUser,
) -> None:
    await service.leave_waitlist(current_user.id, zone)
