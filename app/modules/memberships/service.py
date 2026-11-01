from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.auth import User
from app.models.memberships import (
    Membership,
    MembershipEntitlement,
    MembershipPlan,
    MembershipStatus,
    PlanEntitlement,
)
from app.models.notifications import NotificationType
from app.modules.memberships.payment_gateway import PaymentGateway, PaymentResult, PaymentStatus
from app.modules.memberships.states import state_of
from app.modules.notifications.service import NotificationEvent, NotificationObserver
from app.shared.pagination import (
    CursorDirection,
    CursorMeta,
    CursorParams,
    CursorResult,
    PageMeta,
    PageParams,
    PageResult,
    encode_cursor,
)

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
        self,
        payment_gateway: PaymentGateway | None = None,
        notifications: NotificationObserver | None = None,
    ) -> None:
        self.payment_gateway = payment_gateway
        self.notifications = notifications

    async def list_for_user(
        self, session: AsyncSession, user_id: UUID, params: CursorParams
    ) -> CursorResult[Membership]:
        statement = select(Membership).where(Membership.user_id == user_id)
        if params.values:
            if len(params.values) != 2 or not isinstance(params.values[0], str):
                raise AppError("cursor is invalid", HTTPStatus.UNPROCESSABLE_ENTITY)
            try:
                ends_on = date.fromisoformat(params.values[0])
                membership_id = int(params.values[1])
            except (TypeError, ValueError) as error:
                raise AppError("cursor is invalid", HTTPStatus.UNPROCESSABLE_ENTITY) from error
            if params.direction == CursorDirection.NEXT:
                statement = statement.where(
                    (Membership.ends_on < ends_on)
                    | ((Membership.ends_on == ends_on) & (Membership.id < membership_id))
                ).order_by(Membership.ends_on.desc(), Membership.id.desc())
            else:
                statement = statement.where(
                    (Membership.ends_on > ends_on)
                    | ((Membership.ends_on == ends_on) & (Membership.id > membership_id))
                ).order_by(Membership.ends_on, Membership.id)
        elif params.direction == CursorDirection.PREVIOUS:
            raise AppError(
                "cursor is required for previous navigation", HTTPStatus.UNPROCESSABLE_ENTITY
            )
        else:
            statement = statement.order_by(Membership.ends_on.desc(), Membership.id.desc())
        rows = list((await session.scalars(statement.limit(params.limit + 1))).all())
        has_more = len(rows) > params.limit
        items = rows[: params.limit]
        if params.direction == CursorDirection.PREVIOUS:
            items.reverse()
        has_next = (
            has_more if params.direction == CursorDirection.NEXT else params.cursor is not None
        )
        has_previous = (
            params.cursor is not None if params.direction == CursorDirection.NEXT else has_more
        )
        return CursorResult(
            items=items,
            meta=CursorMeta(
                limit=params.limit,
                next_cursor=(
                    encode_cursor(items[-1].ends_on.isoformat(), items[-1].id)
                    if has_next and items
                    else None
                ),
                previous_cursor=(
                    encode_cursor(items[0].ends_on.isoformat(), items[0].id)
                    if has_previous and items
                    else None
                ),
                has_next=has_next,
                has_previous=has_previous,
            ),
        )

    async def list_plans(
        self, session: AsyncSession, params: PageParams
    ) -> PageResult[MembershipPlan]:
        filters = (MembershipPlan.is_active.is_(True), MembershipPlan.price_minor > 0)
        total_count = (
            await session.scalar(select(func.count(MembershipPlan.id)).where(*filters)) or 0
        )
        statement = (
            select(MembershipPlan)
            .where(*filters)
            .options(selectinload(MembershipPlan.entitlements))
            .order_by(MembershipPlan.price_minor, MembershipPlan.id)
            .offset(params.offset)
            .limit(params.limit)
        )
        return PageResult(
            items=list((await session.scalars(statement)).all()),
            meta=PageMeta(
                page=params.page,
                limit=params.limit,
                total_pages=(total_count + params.limit - 1) // params.limit,
                total_count=total_count,
            ),
        )

    async def list_all_plans(
        self, session: AsyncSession, params: PageParams
    ) -> PageResult[MembershipPlan]:
        """Every plan, including deactivated ones, for managers."""
        total_count = await session.scalar(select(func.count(MembershipPlan.id))) or 0
        statement = (
            select(MembershipPlan)
            .options(selectinload(MembershipPlan.entitlements))
            .order_by(
                MembershipPlan.is_active.desc(), MembershipPlan.price_minor, MembershipPlan.id
            )
            .offset(params.offset)
            .limit(params.limit)
        )
        return PageResult(
            items=list((await session.scalars(statement)).all()),
            meta=PageMeta(
                page=params.page,
                limit=params.limit,
                total_pages=(total_count + params.limit - 1) // params.limit,
                total_count=total_count,
            ),
        )

    async def get_plan(self, session: AsyncSession, plan_id: int) -> MembershipPlan:
        plan = await session.scalar(
            select(MembershipPlan)
            .where(MembershipPlan.id == plan_id)
            .options(selectinload(MembershipPlan.entitlements))
        )
        if plan is None:
            raise AppError("membership plan was not found", HTTPStatus.NOT_FOUND)
        return plan

    async def create_plan(
        self,
        session: AsyncSession,
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
        await self.ensure_plan_name_free(session, name)
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
        session.add(plan)
        await self._flush_plan_change(session)
        return await self.get_plan(session, plan.id)

    async def update_plan(
        self,
        session: AsyncSession,
        plan_id: int,
        *,
        entitlements: set[MembershipEntitlement] | None = None,
        **changes: object,
    ) -> MembershipPlan:
        """Change the given plan fields. Existing memberships keep their dates; new limits
        and entitlements apply to their next booking or check-in."""
        unknown = changes.keys() - EDITABLE_PLAN_FIELDS
        if unknown:
            raise AppError(
                f"cannot change plan fields: {', '.join(sorted(unknown))}",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        plan = await self.get_plan(session, plan_id)
        new_name = changes.get("name")
        if isinstance(new_name, str) and new_name.lower() != plan.name.lower():
            await self.ensure_plan_name_free(session, new_name, ignore_plan_id=plan.id)
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
        await self._flush_plan_change(session)
        return await self.get_plan(session, plan.id)

    async def deactivate_plan(self, session: AsyncSession, plan_id: int) -> None:
        """Take a plan off sale. Current members keep it until it ends; it cannot be renewed."""
        plan = await self.get_plan(session, plan_id)
        plan.is_active = False

    async def ensure_plan_name_free(
        self, session: AsyncSession, name: str, ignore_plan_id: int | None = None
    ) -> None:
        statement = select(MembershipPlan.id).where(func.lower(MembershipPlan.name) == name.lower())
        if ignore_plan_id is not None:
            statement = statement.where(MembershipPlan.id != ignore_plan_id)
        if await session.scalar(statement) is not None:
            raise AppError("a plan with this name already exists", HTTPStatus.CONFLICT)

    async def _flush_plan_change(self, session: AsyncSession) -> None:
        try:
            await session.flush()
        except IntegrityError as error:
            raise AppError("a plan with this name already exists", HTTPStatus.CONFLICT) from error

    async def purchase(self, session: AsyncSession, user_id: UUID, plan_id: int) -> PurchaseResult:
        if self.payment_gateway is None:
            raise AppError("payment gateway is not configured", HTTPStatus.INTERNAL_SERVER_ERROR)

        # A plan without a price is not on sale, so it is treated as not found.
        plan = await session.scalar(
            select(MembershipPlan).where(
                MembershipPlan.id == plan_id,
                MembershipPlan.is_active.is_(True),
                MembershipPlan.price_minor > 0,
            )
        )
        if plan is None:
            raise AppError("membership plan was not found", HTTPStatus.NOT_FOUND)

        # Lock this member's row until the transaction ends, so two purchases for the
        # same member run one after the other and the second sees the first membership.
        await session.execute(select(User.id).where(User.id == user_id).with_for_update())
        today = datetime.now(UTC).date()
        if await self.has_pending_membership(session, user_id):
            raise AppError("you already have a payment awaiting completion", HTTPStatus.CONFLICT)
        if await self.has_active_membership(session, user_id, today):
            raise AppError("you already have an active membership", HTTPStatus.CONFLICT)

        payment = await self.payment_gateway.create_checkout(
            plan.price_minor, plan.currency, plan_name=plan.name
        )
        if payment.status == PaymentStatus.DECLINED:
            raise AppError("payment was declined", HTTPStatus.PAYMENT_REQUIRED)
        if payment.status != PaymentStatus.PENDING:
            raise AppError("payment could not be started", HTTPStatus.PAYMENT_REQUIRED)

        membership = Membership(
            user_id=user_id,
            plan_id=plan.id,
            status=MembershipStatus.PENDING,
            starts_on=today,
            # ends_on is inclusive, so a 30-day plan bought today ends on day 30.
            ends_on=today + timedelta(days=plan.duration_days - 1),
            payment_reference=payment.reference,
            stripe_session_id=payment.reference,
        )
        session.add(membership)
        await session.flush()
        return PurchaseResult(membership=membership, plan=plan, payment=payment)

    async def latest_membership(
        self, session: AsyncSession, user_id: UUID, statuses: tuple[MembershipStatus, ...]
    ) -> Membership | None:
        statement = (
            select(Membership)
            .where(Membership.user_id == user_id, Membership.status.in_(statuses))
            .options(selectinload(Membership.plan))
            .order_by(Membership.id.desc())
            .limit(1)
        )
        return await session.scalar(statement)

    async def cancel(
        self, session: AsyncSession, pending_notifications: list, user_id: UUID
    ) -> Membership:
        """Cancel the member's currently active membership."""
        await self.lock_member(session, user_id)
        today = datetime.now(UTC).date()
        membership = await session.scalar(
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.starts_on <= today,
                Membership.ends_on >= today,
            )
            .options(selectinload(Membership.plan))
            .order_by(Membership.id.desc())
            .limit(1)
        )
        if membership is None:
            raise AppError("you do not have an active membership", HTTPStatus.NOT_FOUND)
        state_of(membership, today).cancel(membership)
        await self._record(
            session,
            pending_notifications,
            user_id,
            NotificationType.MEMBERSHIP_CANCELLED,
            {"membership_id": membership.id, "ends_on": membership.ends_on.isoformat()},
        )
        return membership

    async def renew(
        self, session: AsyncSession, pending_notifications: list, user_id: UUID
    ) -> PurchaseResult:
        """Renew the member's latest membership on the same plan.

        What a renewal does depends on the membership's state (see states.py).
        The new dates are worked out first and only applied once payment succeeds.
        """
        if self.payment_gateway is None:
            raise AppError("payment gateway is not configured", HTTPStatus.INTERNAL_SERVER_ERROR)

        await self.lock_member(session, user_id)
        today = datetime.now(UTC).date()
        if await self.has_pending_membership(session, user_id):
            raise AppError("you already have a payment awaiting completion", HTTPStatus.CONFLICT)
        membership = await self.latest_membership(
            session, user_id, (MembershipStatus.ACTIVE, MembershipStatus.EXPIRED)
        )
        if membership is None:
            raise AppError("you do not have a membership to renew", HTTPStatus.NOT_FOUND)
        plan = membership.plan
        if not plan.is_active or plan.price_minor <= 0:
            raise AppError(
                "this plan is no longer on sale, please choose another", HTTPStatus.NOT_FOUND
            )
        terms = state_of(membership, today).renewal_terms(membership, plan.duration_days, today)

        payment = await self.payment_gateway.create_checkout(
            plan.price_minor, plan.currency, plan_name=plan.name
        )
        if payment.status == PaymentStatus.DECLINED:
            raise AppError("payment was declined", HTTPStatus.PAYMENT_REQUIRED)
        if payment.status != PaymentStatus.PENDING:
            raise AppError("payment could not be started", HTTPStatus.PAYMENT_REQUIRED)

        # Do not change the current membership while Checkout is outstanding.
        # On a successful webhook, this row becomes active and its precomputed
        # renewal dates take effect.
        membership = Membership(
            user_id=user_id,
            plan_id=plan.id,
            status=MembershipStatus.PENDING,
            starts_on=terms.starts_on,
            ends_on=terms.ends_on,
            payment_reference=payment.reference,
            stripe_session_id=payment.reference,
        )
        session.add(membership)
        await session.flush()
        return PurchaseResult(membership=membership, plan=plan, payment=payment)

    async def _record(
        self,
        session: AsyncSession,
        pending_notifications: list,
        user_id: UUID,
        event_type: NotificationType,
        payload: dict[str, object],
    ) -> None:
        if self.notifications is not None:
            await self.notifications.observe(
                session,
                pending_notifications,
                NotificationEvent(user_id=user_id, event_type=event_type, payload=payload),
            )

    async def lock_member(self, session: AsyncSession, user_id: UUID) -> None:
        # Lock this member's row until the transaction ends, so two changes to the
        # same member's membership run one after the other.
        await session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def booking_membership(
        self, session: AsyncSession, user_id: UUID, on_date: date
    ) -> Membership | None:
        """Load the current membership and its plan rules without lazy database access."""
        return await session.scalar(
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

    async def has_active_membership(
        self, session: AsyncSession, user_id: UUID, on_date: date | None = None
    ) -> bool:
        active_date = on_date or datetime.now(UTC).date()
        statement = select(Membership.id).where(
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.starts_on <= active_date,
            Membership.ends_on >= active_date,
        )
        return await session.scalar(statement) is not None

    async def has_pending_membership(self, session: AsyncSession, user_id: UUID) -> bool:
        return (
            await session.scalar(
                select(Membership.id).where(
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.PENDING,
                )
            )
            is not None
        )

    async def has_entitlement(
        self,
        session: AsyncSession,
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
        return await session.scalar(statement) is not None
