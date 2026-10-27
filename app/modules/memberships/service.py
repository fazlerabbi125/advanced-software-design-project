from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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


class PlanNameTakenError(ValueError):
    pass


# Plan columns a manager may set. Entitlements are handled separately because they are rows.
EDITABLE_PLAN_FIELDS = frozenset(
    {
        "name",
        "price_minor",
        "currency",
        "duration_days",
        "booking_window_days",
        "weekly_booking_limit",
        "is_active",
    }
)


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

    async def list_for_user(self, user_id: UUID) -> list[Membership]:
        statement = (
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.ends_on.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def list_plans(self) -> list[MembershipPlan]:
        statement = (
            select(MembershipPlan)
            .where(MembershipPlan.is_active.is_(True), MembershipPlan.price_minor > 0)
            .options(selectinload(MembershipPlan.entitlements))
            .order_by(MembershipPlan.price_minor)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_all_plans(self) -> list[MembershipPlan]:
        """Every plan, including deactivated ones, for managers."""
        statement = (
            select(MembershipPlan)
            .options(selectinload(MembershipPlan.entitlements))
            .order_by(MembershipPlan.is_active.desc(), MembershipPlan.price_minor)
        )
        return list((await self.session.scalars(statement)).all())

    async def get_plan(self, plan_id: int) -> MembershipPlan:
        plan = await self.session.scalar(
            select(MembershipPlan)
            .where(MembershipPlan.id == plan_id)
            .options(selectinload(MembershipPlan.entitlements))
        )
        if plan is None:
            raise PlanNotFoundError("membership plan was not found")
        return plan

    async def create_plan(
        self,
        *,
        name: str,
        price_minor: int,
        currency: str,
        duration_days: int,
        booking_window_days: int,
        weekly_booking_limit: int,
        entitlements: set[MembershipEntitlement],
    ) -> MembershipPlan:
        """Add a plan as data. Booking and access rules read its limits and entitlements,
        so a new plan needs no code change."""
        await self.ensure_plan_name_free(name)
        plan = MembershipPlan(
            name=name,
            is_active=True,
            price_minor=price_minor,
            currency=currency,
            duration_days=duration_days,
            booking_window_days=booking_window_days,
            weekly_booking_limit=weekly_booking_limit,
            entitlements=[PlanEntitlement(entitlement=item) for item in sorted(entitlements)],
        )
        self.session.add(plan)
        await self.commit_plan_change()
        return await self.get_plan(plan.id)

    async def update_plan(
        self,
        plan_id: int,
        *,
        entitlements: set[MembershipEntitlement] | None = None,
        **changes: object,
    ) -> MembershipPlan:
        """Change the given plan fields. Existing memberships keep their dates; new limits
        and entitlements apply to their next booking or check-in."""
        unknown = changes.keys() - EDITABLE_PLAN_FIELDS
        if unknown:
            raise ValueError(f"cannot change plan fields: {', '.join(sorted(unknown))}")
        plan = await self.get_plan(plan_id)
        new_name = changes.get("name")
        if isinstance(new_name, str) and new_name.lower() != plan.name.lower():
            await self.ensure_plan_name_free(new_name, ignore_plan_id=plan.id)
        for field, value in changes.items():
            setattr(plan, field, value)
        if entitlements is not None:
            # Remove and add only the differences, so unchanged rows are never deleted and
            # re-inserted against the (plan, entitlement) unique constraint.
            current = {entry.entitlement: entry for entry in plan.entitlements}
            for entitlement, entry in current.items():
                if entitlement not in entitlements:
                    plan.entitlements.remove(entry)
            for entitlement in sorted(entitlements - current.keys()):
                plan.entitlements.append(PlanEntitlement(entitlement=entitlement))
        await self.commit_plan_change()
        return await self.get_plan(plan.id)

    async def deactivate_plan(self, plan_id: int) -> None:
        """Take a plan off sale. Current members keep it until it ends; it cannot be renewed."""
        plan = await self.get_plan(plan_id)
        plan.is_active = False
        await self.session.commit()

    async def ensure_plan_name_free(self, name: str, ignore_plan_id: int | None = None) -> None:
        statement = select(MembershipPlan.id).where(func.lower(MembershipPlan.name) == name.lower())
        if ignore_plan_id is not None:
            statement = statement.where(MembershipPlan.id != ignore_plan_id)
        if await self.session.scalar(statement) is not None:
            raise PlanNameTakenError("a plan with this name already exists")

    async def commit_plan_change(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as error:
            # Another manager saved the same name between the check and this commit.
            await self.session.rollback()
            raise PlanNameTakenError("a plan with this name already exists") from error

    async def purchase(self, user_id: UUID, plan_id: int) -> PurchaseResult:
        if self.payment_gateway is None:
            raise RuntimeError("MembershipService was created without a payment gateway")

        # A plan without a price is not on sale, so it is treated as not found.
        plan = await self.session.scalar(
            select(MembershipPlan).where(
                MembershipPlan.id == plan_id,
                MembershipPlan.is_active.is_(True),
                MembershipPlan.price_minor > 0,
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

    async def latest_membership(self, user_id: UUID) -> Membership | None:
        statement = (
            select(Membership)
            .where(Membership.user_id == user_id)
            .options(selectinload(Membership.plan))
            .order_by(Membership.id.desc())
            .limit(1)
        )
        return await self.session.scalar(statement)

    async def cancel(self, user_id: UUID) -> Membership:
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

    async def renew(self, user_id: UUID) -> PurchaseResult:
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

    async def lock_member(self, user_id: UUID) -> None:
        # Lock this member's row until the transaction ends, so two changes to the
        # same member's membership run one after the other.
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())
    async def booking_membership(self, user_id: UUID, on_date: date) -> Membership | None:
        """Load the current membership and its plan rules without lazy database access."""
        return await self.session.scalar(
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.starts_on <= on_date,
                Membership.ends_on >= on_date,
            )
            .options(selectinload(Membership.plan).selectinload(MembershipPlan.entitlements))
            .order_by(Membership.ends_on.desc(), Membership.id.desc())
            .limit(1)
        )

    async def has_active_membership(self, user_id: UUID, on_date: date | None = None) -> bool:
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
        user_id: UUID,
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
