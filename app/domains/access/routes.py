from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser, require_roles
from app.domains.access.dependencies import AccessServiceDependency
from app.models.access import AccessEvent
from app.models.auth import UserRole

router = APIRouter(prefix="/access", tags=["access"])


class CheckInRequest(BaseModel):
    member_id: int | None = Field(default=None, gt=0)
    zone: str = Field(default="gym_floor", min_length=1, max_length=100)


class AccessLogResponse(BaseModel):
    id: int
    member_id: int
    event: str
    zone: str
    source: str
    occurred_at: datetime


@router.post("/check-in", response_model=AccessLogResponse, status_code=status.HTTP_201_CREATED)
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
