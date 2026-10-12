from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.memberships.payment_gateway import PaymentGateway, PaymentResult, PaymentStatus
from app.models.memberships import (
    Membership,
    MembershipEntitlement,
    MembershipPlan,
    MembershipStatus,
    PlanEntitlement,
)


class PlanNotFoundError(ValueError):
    pass


class ActiveMembershipExistsError(ValueError):
    pass


class PaymentDeclinedError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PurchaseResult:
    membership: Membership
    plan: MembershipPlan
    payment: PaymentResult


class MembershipService:
    def __init__(
        self, session: AsyncSession, payment_gateway: PaymentGateway | None = None
    ) -> None:
        self.session = session
        self.payment_gateway = payment_gateway

    async def list_for_user(self, user_id: int) -> list[Membership]:
        statement = (
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.ends_on.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def list_plans(self) -> list[MembershipPlan]:
        statement = (
            select(MembershipPlan)
            .where(MembershipPlan.is_active.is_(True))
            .options(selectinload(MembershipPlan.entitlements))
            .order_by(MembershipPlan.price_minor)
        )
        return list((await self.session.scalars(statement)).all())

    async def purchase(self, user_id: int, plan_id: int) -> PurchaseResult:
        if self.payment_gateway is None:
            raise RuntimeError("MembershipService was created without a payment gateway")

        plan = await self.session.scalar(
            select(MembershipPlan).where(
                MembershipPlan.id == plan_id, MembershipPlan.is_active.is_(True)
            )
        )
        if plan is None:
            raise PlanNotFoundError("membership plan was not found")

        today = datetime.now(UTC).date()
        if await self.has_active_membership(user_id, today):
            raise ActiveMembershipExistsError("you already have an active membership")

        payment = self.payment_gateway.charge(plan.price_minor, plan.currency)
        if payment.status != PaymentStatus.APPROVED:
            raise PaymentDeclinedError("payment was declined")

        membership = Membership(
            user_id=user_id,
            plan_id=plan.id,
            status=MembershipStatus.ACTIVE,
            starts_on=today,
            # ends_on is inclusive, so a 30-day plan bought today ends on day 30.
            ends_on=today + timedelta(days=plan.duration_days - 1),
            payment_reference=payment.reference,
        )
        self.session.add(membership)
        await self.session.commit()
        await self.session.refresh(membership)
        return PurchaseResult(membership=membership, plan=plan, payment=payment)

    async def has_active_membership(self, user_id: int, on_date: date | None = None) -> bool:
        active_date = on_date or datetime.now(UTC).date()
        statement = select(Membership.id).where(
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.starts_on <= active_date,
            Membership.ends_on >= active_date,
        )
        return await self.session.scalar(statement) is not None

    async def has_entitlement(
        self,
        user_id: int,
        entitlement: MembershipEntitlement,
        on_date: date | None = None,
    ) -> bool:
        active_date = on_date or datetime.now(UTC).date()
        statement = (
            select(Membership.id)
            .join(PlanEntitlement, PlanEntitlement.plan_id == Membership.plan_id)
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.starts_on <= active_date,
                Membership.ends_on >= active_date,
                PlanEntitlement.entitlement == entitlement,
            )
        )
        return await self.session.scalar(statement) is not None
