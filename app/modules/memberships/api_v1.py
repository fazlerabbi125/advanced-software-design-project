from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app.models.memberships import Membership, MembershipPlan
from app.modules.auth.dependencies import CurrentUser
from app.modules.memberships.dependencies import MembershipServiceDependency
from app.modules.memberships.schemas import (
    MembershipResponse,
    PlanResponse,
    PurchaseRequest,
    PurchaseResponse,
)
from app.modules.memberships.service import (
    ActiveMembershipExistsError,
    MembershipNotFoundError,
    PaymentDeclinedError,
    PlanNotFoundError,
)
from app.modules.memberships.states import MembershipActionError, state_of

router = APIRouter(prefix="/memberships", tags=["memberships"])


def membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        plan_id=membership.plan_id,
        # The current state, so a membership past its end date shows as expired.
        status=state_of(membership, datetime.now(UTC).date()).status.value,
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


@router.post("/me/cancel", response_model=MembershipResponse)
async def cancel_my_membership(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> MembershipResponse:
    """Cancel your current membership. Access stops straight away; there is no refund."""
    try:
        membership = await service.cancel(current_user.id)
    except MembershipNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MembershipActionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return membership_response(membership)


@router.post("/me/renew", response_model=PurchaseResponse)
async def renew_my_membership(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> PurchaseResponse:
    """Renew your membership on the same plan.

    An active membership gets another period added after its current end date; an
    expired one starts again from today. A cancelled membership cannot be renewed.
    """
    try:
        result = await service.renew(current_user.id)
    except (MembershipNotFoundError, PlanNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MembershipActionError as error:
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
