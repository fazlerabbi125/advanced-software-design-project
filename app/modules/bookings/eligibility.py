"""Collecting Chain of Responsibility: each handler checks, then forwards.

Handlers are side-effect free. The service loads one snapshot and owns locking and
persistence. Add a rule by implementing check() and registering it in DEFAULT_RULES.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.bookings import Booking, BookingResourceType, BookingStatus
from app.models.memberships import Membership, MembershipEntitlement, MembershipStatus
from app.utils.constants import NO_SHOW_PENALTY_DAYS, NO_SHOW_PENALTY_LIMIT

REQUIRED_ENTITLEMENTS = {
    BookingResourceType.CLASS: MembershipEntitlement.CLASS_BOOKING,
    BookingResourceType.POOL: MembershipEntitlement.POOL_BOOKING,
    BookingResourceType.PERSONAL_TRAINING: MembershipEntitlement.PERSONAL_TRAINING,
}


@dataclass(frozen=True)
class EligibilityFailure:
    code: str
    message: str


class BookingEligibilityError(ValueError):
    def __init__(self, failures: Sequence[EligibilityFailure]) -> None:
        self.failures = tuple(failures)
        super().__init__("; ".join(failure.message for failure in failures))


@dataclass(frozen=True)
class BookingContext:
    now: datetime
    starts_at: datetime
    resource_type: BookingResourceType
    membership: Membership | None
    bookings: Sequence[Booking]
    has_unresolved_no_shows: bool = False


def week_bounds(starts_at: datetime) -> tuple[datetime, datetime]:
    """The requested session's Monday–Sunday week, in UTC."""
    start = starts_at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    return start, start + timedelta(days=7)


class EligibilityRule(ABC):
    def __init__(self, successor: EligibilityRule | None = None) -> None:
        self.successor = successor

    def handle(self, context: BookingContext) -> list[EligibilityFailure]:
        failure = self.check(context)
        failures = [failure] if failure is not None else []
        if self.successor is not None:
            failures.extend(self.successor.handle(context))
        return failures

    @abstractmethod
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        """Return this rule's failure, or None; never stop subsequent checks."""


class FutureSessionRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        if context.starts_at <= context.now:
            return EligibilityFailure("session_started", "booking must be in the future")
        return None


class ActiveMembershipRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        membership = context.membership
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or not membership.starts_on <= context.now.date() <= membership.ends_on
            or not membership.starts_on <= context.starts_at.date() <= membership.ends_on
        ):
            return EligibilityFailure(
                "membership_inactive", "an active membership covering the session is required"
            )
        return None


class EntitlementRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        if context.membership is None:
            return None  # No plan to evaluate; ActiveMembershipRule reports the missing membership.
        entitlements = {entry.entitlement for entry in context.membership.plan.entitlements}
        if REQUIRED_ENTITLEMENTS[context.resource_type] not in entitlements:
            return EligibilityFailure(
                "plan_entitlement", "your membership plan does not allow this booking type"
            )
        return None


class BookingWindowRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        if context.membership is None:
            return None
        days = context.membership.plan.booking_window_days
        if context.starts_at > context.now + timedelta(days=days):
            return EligibilityFailure("booking_window", f"booking is outside the {days}-day window")
        return None


class WeeklyLimitRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        if context.membership is None:
            return None
        start, end = week_bounds(context.starts_at)
        count = sum(
            booking.status != BookingStatus.CANCELLED and start <= booking.starts_at < end
            for booking in context.bookings
        )
        limit = context.membership.plan.weekly_booking_limit
        if count >= limit:
            return EligibilityFailure("weekly_limit", f"weekly booking limit of {limit} reached")
        return None


class SameStartRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        # Checked-in and no-show bookings still used the slot, so only cancelled ones are free.
        if any(
            booking.status != BookingStatus.CANCELLED and booking.starts_at == context.starts_at
            for booking in context.bookings
        ):
            return EligibilityFailure("time_conflict", "you already have a booking at this time")
        return None


class NoShowPenaltyRule(EligibilityRule):
    def check(self, context: BookingContext) -> EligibilityFailure | None:
        if context.has_unresolved_no_shows:
            return EligibilityFailure(
                "no_show_penalty",
                f"bookings are paused after {NO_SHOW_PENALTY_LIMIT} missed sessions "
                f"in the last {NO_SHOW_PENALTY_DAYS} days",
            )
        return None


DEFAULT_RULES = (
    FutureSessionRule,
    ActiveMembershipRule,
    EntitlementRule,
    BookingWindowRule,
    WeeklyLimitRule,
    SameStartRule,
    NoShowPenaltyRule,
)


def build_eligibility_chain(
    rules: Sequence[type[EligibilityRule]] = DEFAULT_RULES,
) -> EligibilityRule:
    if not rules:
        raise ValueError("the eligibility chain must contain at least one rule")
    successor = None
    for rule in reversed(rules):
        successor = rule(successor)
    return successor
