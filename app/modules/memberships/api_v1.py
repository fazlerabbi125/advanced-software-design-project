from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import DbSession
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
    PendingMembershipExistsError,
    PlanNameTakenError,
    PlanNotFoundError,
)
from app.modules.memberships.states import MembershipActionError

router = APIRouter(prefix="/memberships", tags=["memberships"])


@router.get(
    "/plans", response_model=list[PlanResponse], description="List plans currently on sale."
)
async def list_plans(service: MembershipServiceDependency) -> Any:
    return await service.list_plans()


@router.get(
    "/plans/all", response_model=list[PlanResponse], description="List all plans for managers."
)
async def list_all_plans(
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> Any:
    return await service.list_all_plans()


@router.post(
    "/plans",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    description="Create a membership plan.",
)
async def create_plan(
    payload: CreatePlanRequest,
    session: DbSession,
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> Any:
    try:
        plan = await service.create_plan(**payload.model_dump())
        await session.commit()
    except PlanNameTakenError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise
    return plan


@router.patch(
    "/plans/{plan_id}", response_model=PlanResponse, description="Update a membership plan."
)
async def update_plan(
    plan_id: int,
    payload: UpdatePlanRequest,
    session: DbSession,
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> Any:
    changes = payload.model_dump(exclude_none=True)
    entitlements = changes.pop("entitlements", None)
    try:
        plan = await service.update_plan(plan_id, entitlements=entitlements, **changes)
    except PlanNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PlanNameTakenError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return plan


@router.delete(
    "/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, description="Take a plan off sale."
)
async def deactivate_plan(
    plan_id: int,
    session: DbSession,
    service: MembershipServiceDependency,
    _: Annotated[object, Depends(require_roles(UserRole.MANAGER))],
) -> None:
    try:
        await service.deactivate_plan(plan_id)
        await session.commit()
    except PlanNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/purchase",
    response_model=PurchaseResponse,
    status_code=status.HTTP_201_CREATED,
    description="Create a Stripe Checkout session for a plan.",
)
async def purchase_membership(
    payload: PurchaseRequest,
    current_user: CurrentUser,
    session: DbSession,
    service: MembershipServiceDependency,
) -> Any:
    try:
        result = await service.purchase(current_user.id, payload.plan_id)
    except PlanNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (ActiveMembershipExistsError, PendingMembershipExistsError) as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentDeclinedError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(error)
        ) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return result


@router.get("/me", response_model=list[MembershipResponse], description="List your memberships.")
async def list_my_memberships(
    current_user: CurrentUser, service: MembershipServiceDependency
) -> Any:
    return await service.list_for_user(current_user.id)


@router.post(
    "/me/cancel", response_model=MembershipResponse, description="Cancel your latest membership."
)
async def cancel_my_membership(
    current_user: CurrentUser, session: DbSession, service: MembershipServiceDependency
) -> Any:
    try:
        membership = await service.cancel(current_user.id)
    except MembershipNotFoundError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MembershipActionError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return membership


@router.post(
    "/me/renew",
    response_model=PurchaseResponse,
    description="Create Checkout for membership renewal.",
)
async def renew_my_membership(
    current_user: CurrentUser, session: DbSession, service: MembershipServiceDependency
) -> Any:
    try:
        result = await service.renew(current_user.id)
    except (MembershipNotFoundError, PlanNotFoundError) as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MembershipActionError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PendingMembershipExistsError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentDeclinedError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(error)
        ) from error
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return result
