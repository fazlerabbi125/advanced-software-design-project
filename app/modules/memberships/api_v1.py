from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.auth import UserRole
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.memberships.dependencies import MembershipServiceDependency
from app.modules.memberships.schemas import (
    CreatePlanRequest,
    MembershipResponse,
    PlanResponse,
    PurchaseRequest,
    PurchaseResponse,
    UpdatePlanRequest,
)
from app.modules.memberships.service import (
    ActiveMembershipExistsError,
    MembershipNotFoundError,
    PaymentDeclinedError,
    PlanNameTakenError,
    PlanNotFoundError,
)
from app.modules.memberships.states import MembershipActionError

router = APIRouter(prefix="/memberships", tags=["memberships"])


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(service: MembershipServiceDependency) -> Any:
    return await service.list_plans()


@router.get("/plans/all", response_model=list[PlanResponse])
async def list_all_plans(
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> Any:
    """Every plan, including ones taken off sale (managers only)."""
    return await service.list_all_plans()


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: CreatePlanRequest,
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> Any:
    """Create a plan with its price, booking limits and entitlements (managers only)."""
    try:
        plan = await service.create_plan(**payload.model_dump())
    except PlanNameTakenError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: int,
    payload: UpdatePlanRequest,
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> Any:
    """Change only the fields sent (managers only). Sending entitlements replaces the set."""
    changes = payload.model_dump(exclude_none=True)
    entitlements = changes.pop("entitlements", None)
    try:
        plan = await service.update_plan(plan_id, entitlements=entitlements, **changes)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PlanNameTakenError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return plan


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_plan(
    plan_id: int,
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> None:
    """Take a plan off sale (managers only). Current members keep it until it ends."""
    try:
        await service.deactivate_plan(plan_id)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/purchase", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
async def purchase_membership(
    payload: PurchaseRequest, current_user: CurrentUser, service: MembershipServiceDependency
) -> Any:
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
    return result


@router.get("/me", response_model=list[MembershipResponse])
async def list_my_memberships(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> Any:
    return await service.list_for_user(current_user.id)


@router.post("/me/cancel", response_model=MembershipResponse)
async def cancel_my_membership(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> Any:
    """Cancel your current membership. Access stops straight away; there is no refund."""
    try:
        membership = await service.cancel(current_user.id)
    except MembershipNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MembershipActionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return membership


@router.post("/me/renew", response_model=PurchaseResponse)
async def renew_my_membership(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> Any:
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
    return result
