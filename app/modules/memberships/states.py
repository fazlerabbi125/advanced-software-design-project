"""Membership lifecycle, using the State pattern.

A membership is Active, Expired or Cancelled. Each state is its own class, and the
service asks the membership's current state what is allowed instead of checking the
status with if/else in many places. The same action (renew, cancel) therefore
behaves differently depending on the state the membership is in.

    Active --(end date passes)--> Expired --(renew)--> Active
    Active --(cancel)--> Cancelled
    Active --(renew)--> Active, with the end date pushed back
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta

from app.models.memberships import Membership, MembershipStatus


class MembershipActionError(ValueError):
    """Raised when an action is not allowed in the membership's current state."""


@dataclass(frozen=True, slots=True)
class RenewalTerms:
    starts_on: date
    ends_on: date


class MembershipState(ABC):
    status: MembershipStatus

    @abstractmethod
    def cancel(self, membership: Membership) -> None:
        """Cancel the membership, or raise MembershipActionError if not allowed."""

    @abstractmethod
    def renewal_terms(
        self, membership: Membership, duration_days: int, today: date
    ) -> RenewalTerms:
        """Work out the new dates for a renewal, or raise MembershipActionError.

        This only calculates; the caller takes payment and then applies the terms,
        so nothing changes if the payment fails.
        """


class ActiveState(MembershipState):
    status = MembershipStatus.ACTIVE

    def cancel(self, membership: Membership) -> None:
        # No refund: access stops straight away.
        membership.status = MembershipStatus.CANCELLED

    def renewal_terms(
        self, membership: Membership, duration_days: int, today: date
    ) -> RenewalTerms:
        # Renewing early adds the new period after the current end date, so the
        # member keeps the days they have already paid for.
        return RenewalTerms(
            starts_on=membership.starts_on,
            ends_on=membership.ends_on + timedelta(days=duration_days),
        )


class ExpiredState(MembershipState):
    status = MembershipStatus.EXPIRED

    def cancel(self, membership: Membership) -> None:
        raise MembershipActionError("an expired membership cannot be cancelled")

    def renewal_terms(
        self, membership: Membership, duration_days: int, today: date
    ) -> RenewalTerms:
        # A lapsed membership starts a fresh period from today.
        return RenewalTerms(starts_on=today, ends_on=today + timedelta(days=duration_days - 1))



class PendingState(MembershipState):
    status = MembershipStatus.PENDING

    def cancel(self, membership: Membership) -> None:
        membership.status = MembershipStatus.CANCELLED

    def renewal_terms(
        self, membership: Membership, duration_days: int, today: date
    ) -> RenewalTerms:
        raise MembershipActionError("A pending membership cannot be renewed")


class CancelledState(MembershipState):
    status = MembershipStatus.CANCELLED

    def cancel(self, membership: Membership) -> None:
        raise MembershipActionError("this membership is already cancelled")

    def renewal_terms(
        self, membership: Membership, duration_days: int, today: date
    ) -> RenewalTerms:
        raise MembershipActionError(
            "a cancelled membership cannot be renewed, please buy a new plan instead"
        )


ACTIVE = ActiveState()
EXPIRED = ExpiredState()
CANCELLED = CancelledState()
PENDING = PendingState()

def state_of(membership: Membership, today: date) -> MembershipState:
    """The membership's current state. A membership past its end date counts as
    expired even if the database row still says active."""
    if membership.status == MembershipStatus.CANCELLED:
        return CANCELLED
    if membership.status == MembershipStatus.PENDING:
        return PENDING
    if membership.status == MembershipStatus.EXPIRED or membership.ends_on < today:
        return EXPIRED
    return ACTIVE
