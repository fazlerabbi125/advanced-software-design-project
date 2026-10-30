from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import DbSessionDep
from app.core.exceptions import AppError, http_error
from app.models.access import AccessEvent, AccessZone
from app.models.auth import User, UserRole
from app.modules.access.dependencies import (
    AccessServiceDep,
    AuthenticatedScannerDep,
    ScannerCheckInServiceDep,
)
from app.modules.access.schemas import (
    AccessLogResponse,
    CheckInRequest,
    DeviceCheckInRequest,
    ManualCheckInRequest,
    WaitlistPositionResponse,
)
from app.modules.auth.dependencies import CurrentUser, require_roles

router = APIRouter(prefix="/access", tags=["access"])


@router.post(
    "/check-in",
    response_model=AccessLogResponse,
    status_code=status.HTTP_201_CREATED,
    description="Check a member into a gym zone.",
)
async def check_in(
    payload: CheckInRequest,
    session: DbSessionDep,
    service: AccessServiceDep,
    current_user: CurrentUser,
) -> Any:
    member_id = payload.member_id or current_user.id
    if member_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    result = None
    try:
        result = await service.check_in(session, member_id, payload.zone)
        await session.commit()
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        if result is not None and result.took_new_place:
            await service.release_place(member_id, payload.zone)
        raise
    return result.access_log


@router.post(
    "/manual-check-in",
    response_model=AccessLogResponse,
    status_code=status.HTTP_201_CREATED,
    description="Record a staff-authorized manual check-in.",
)
async def manual_check_in(
    payload: ManualCheckInRequest,
    session: DbSessionDep,
    service: AccessServiceDep,
    staff: Annotated[User, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> Any:
    result = None
    try:
        result = await service.check_in(
            session,
            payload.member_id,
            payload.zone,
            source="manual",
            event=AccessEvent.MANUAL_CHECK_IN,
            staff_id=staff.id,
            reason=payload.reason,
        )
        await session.commit()
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        if result is not None and result.took_new_place:
            await service.release_place(payload.member_id, payload.zone)
        raise
    return result.access_log


@router.post(
    "/check-out",
    response_model=AccessLogResponse,
    status_code=status.HTTP_201_CREATED,
    description="Check a member out of a gym zone.",
)
async def check_out(
    payload: CheckInRequest,
    session: DbSessionDep,
    service: AccessServiceDep,
    current_user: CurrentUser,
) -> Any:
    member_id = payload.member_id or current_user.id
    if member_id != current_user.id and current_user.role not in {UserRole.STAFF, UserRole.MANAGER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    try:
        access_log = await service.check_out(session, member_id, payload.zone)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await service.release_place(member_id, payload.zone)
    return access_log


@router.get("/occupancy", description="Show current zone occupancy for staff.")
async def current_occupancy(
    service: AccessServiceDep,
    _: Annotated[object, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))],
) -> dict[str, int]:
    return await service.current_occupancy()


@router.post(
    "/device-check-in",
    response_model=AccessLogResponse,
    status_code=status.HTTP_201_CREATED,
    description="Record a trusted scanner check-in.",
)
async def device_check_in(
    payload: DeviceCheckInRequest,
    session: DbSessionDep,
    service: ScannerCheckInServiceDep,
    scanner: AuthenticatedScannerDep,
) -> Any:
    result = None
    try:
        result = await service.check_in(session, payload, scanner)
        await session.commit()
    except AppError as error:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        if result is not None and result.took_new_place:
            await service.access.release_place(result.access_log.member_id, scanner.zone)
        raise
    return result.access_log


@router.get(
    "/waitlist/{zone}",
    response_model=WaitlistPositionResponse,
    description="Get your zone waitlist position.",
)
async def my_waitlist_position(
    zone: AccessZone,
    service: AccessServiceDep,
    current_user: CurrentUser,
) -> Any:
    position = await service.waitlist_position(current_user.id, zone)
    return {"zone": zone, "position": position}


@router.delete(
    "/waitlist/{zone}", status_code=status.HTTP_204_NO_CONTENT, description="Leave a zone waitlist."
)
async def leave_waitlist(
    zone: AccessZone,
    service: AccessServiceDep,
    current_user: CurrentUser,
) -> None:
    await service.leave_waitlist(current_user.id, zone)
