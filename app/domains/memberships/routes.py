from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.dependencies import CurrentUser
from app.domains.memberships.dependencies import MembershipServiceDependency
from app.models.memberships import Membership

router = APIRouter(prefix="/memberships", tags=["memberships"])


class MembershipResponse(BaseModel):
    id: int
    plan_id: int
    status: str
    starts_on: date
    ends_on: date


def membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        plan_id=membership.plan_id,
        status=membership.status.value,
        starts_on=membership.starts_on,
        ends_on=membership.ends_on,
    )


@router.get("/me", response_model=list[MembershipResponse])
async def list_my_memberships(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> list[MembershipResponse]:
    return [
        membership_response(membership)
        for membership in await service.list_for_user(current_user.id)
    ]
