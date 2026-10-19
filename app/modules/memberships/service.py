from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import User
from app.models.memberships import (
    Membership,
    MembershipEntitlement,
    MembershipPlan,
    MembershipStatus,
    PlanEntitlement,
)
from app.modules.memberships.payment_gateway import PaymentGateway, PaymentResult, PaymentStatus
from app.modules.memberships.states import state_of


class PlanNotFoundError(ValueError):
    pass


class ActiveMembershipExistsError(ValueError):
    pass


class PaymentDeclinedError(ValueError):
    pass


class MembershipNotFoundError(ValueError):
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

        # Lock this member's row until the transaction ends, so two purchases for the
        # same member run one after the other and the second sees the first membership.
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())
        today = datetime.now(UTC).date()
        if await self.has_active_membership(user_id, today):
            await self.session.rollback()
            raise ActiveMembershipExistsError("you already have an active membership")

        payment = self.payment_gateway.charge(plan.price_minor, plan.currency)
        if payment.status != PaymentStatus.APPROVED:
            await self.session.rollback()
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

    async def latest_membership(self, user_id: int) -> Membership | None:
        statement = (
            select(Membership)
            .where(Membership.user_id == user_id)
            .options(selectinload(Membership.plan))
            .order_by(Membership.id.desc())
            .limit(1)
        )
        return await self.session.scalar(statement)

    async def cancel(self, user_id: int) -> Membership:
        """Cancel the member's latest membership, if its current state allows it."""
        await self.lock_member(user_id)
        membership = await self.latest_membership(user_id)
        if membership is None:
            await self.session.rollback()
            raise MembershipNotFoundError("you do not have a membership")
        try:
            state_of(membership, datetime.now(UTC).date()).cancel(membership)
        except ValueError:
            await self.session.rollback()
            raise
        await self.session.commit()
        await self.session.refresh(membership)
        return membership

    async def renew(self, user_id: int) -> PurchaseResult:
        """Renew the member's latest membership on the same plan.

        What a renewal does depends on the membership's state (see states.py).
        The new dates are worked out first and only applied once payment succeeds.
        """
        if self.payment_gateway is None:
            raise RuntimeError("MembershipService was created without a payment gateway")

        await self.lock_member(user_id)
        today = datetime.now(UTC).date()
        membership = await self.latest_membership(user_id)
        if membership is None:
            await self.session.rollback()
            raise MembershipNotFoundError("you do not have a membership to renew")
        plan = membership.plan
        if not plan.is_active or plan.price_minor <= 0:
            await self.session.rollback()
            raise PlanNotFoundError("this plan is no longer on sale, please choose another")
        try:
            terms = state_of(membership, today).renewal_terms(membership, plan.duration_days, today)
        except ValueError:
            await self.session.rollback()
            raise

        payment = self.payment_gateway.charge(plan.price_minor, plan.currency)
        if payment.status != PaymentStatus.APPROVED:
            await self.session.rollback()
            raise PaymentDeclinedError("payment was declined")

        membership.status = MembershipStatus.ACTIVE
        membership.starts_on = terms.starts_on
        membership.ends_on = terms.ends_on
        # Only the latest payment is kept on the membership.
        membership.payment_reference = payment.reference
        await self.session.commit()
        await self.session.refresh(membership)
        return PurchaseResult(membership=membership, plan=plan, payment=payment)

    async def lock_member(self, user_id: int) -> None:
        # Lock this member's row until the transaction ends, so two changes to the
        # same member's membership run one after the other.
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

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
