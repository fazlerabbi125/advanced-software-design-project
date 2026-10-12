from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser
from app.domains.memberships.dependencies import MembershipServiceDependency
from app.domains.memberships.service import (
    ActiveMembershipExistsError,
    PaymentDeclinedError,
    PlanNotFoundError,
)
from app.models.memberships import Membership, MembershipPlan

router = APIRouter(prefix="/memberships", tags=["memberships"])


class MembershipResponse(BaseModel):
    id: int
    plan_id: int
    status: str
    starts_on: date
    ends_on: date


class PlanResponse(BaseModel):
    id: int
    name: str
    price_minor: int
    currency: str
    duration_days: int
    entitlements: list[str]


class PurchaseRequest(BaseModel):
    plan_id: int = Field(gt=0)


class PurchaseResponse(BaseModel):
    membership: MembershipResponse
    plan_name: str
    amount_minor: int
    currency: str
    payment_reference: str


def membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        plan_id=membership.plan_id,
        status=membership.status.value,
        starts_on=membership.starts_on,
        ends_on=membership.ends_on,
    )


def plan_response(plan: MembershipPlan) -> PlanResponse:
    return PlanResponse(
        id=plan.id,
        name=plan.name,
        price_minor=plan.price_minor,
        currency=plan.currency,
        duration_days=plan.duration_days,
        entitlements=sorted(entry.entitlement.value for entry in plan.entitlements),
    )


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(service: MembershipServiceDependency) -> list[PlanResponse]:
    return [plan_response(plan) for plan in await service.list_plans()]


@router.post("/purchase", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
async def purchase_membership(
    payload: PurchaseRequest, current_user: CurrentUser, service: MembershipServiceDependency
) -> PurchaseResponse:
    try:
        result = await service.purchase(current_user.id, payload.plan_id)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ActiveMembershipExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentDeclinedError as error:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(error)
        ) from error
    return PurchaseResponse(
        membership=membership_response(result.membership),
        plan_name=result.plan.name,
        amount_minor=result.payment.amount_minor,
        currency=result.payment.currency,
        payment_reference=result.payment.reference,
    )


@router.get("/me", response_model=list[MembershipResponse])
async def list_my_memberships(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> list[MembershipResponse]:
    return [
        membership_response(membership)
        for membership in await service.list_for_user(current_user.id)
    ]
