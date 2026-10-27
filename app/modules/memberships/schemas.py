from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models.memberships import (
    Membership,
    MembershipEntitlement,
    MembershipPlan,
    MembershipStatus,
)
from app.modules.memberships.states import state_of
from app.shared.constants import (
    MAX_BOOKING_WINDOW_DAYS,
    MAX_PLAN_DURATION_DAYS,
    MAX_PLAN_PRICE_MINOR,
    MAX_WEEKLY_BOOKING_LIMIT,
)


def upper_case(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


PlanName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Currencies the Stripe account accepts; any other code would create a plan nobody can buy.
CurrencyCode = Annotated[Literal["EUR", "GBP", "USD"], BeforeValidator(upper_case)]


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    status: MembershipStatus
    starts_on: date
    ends_on: date

    @model_validator(mode="before")
    @classmethod
    def from_membership(cls, value: Any) -> Any:
        if not isinstance(value, Membership):
            return value
        return {
            "id": value.id,
            "plan_id": value.plan_id,
            "status": state_of(value, datetime.now(UTC).date()).status,
            "starts_on": value.starts_on,
            "ends_on": value.ends_on,
        }


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    price_minor: int
    currency: str
    duration_days: int
    booking_window_days: int
    weekly_booking_limit: int
    is_active: bool
    entitlements: list[MembershipEntitlement]

    @model_validator(mode="before")
    @classmethod
    def from_membership_plan(cls, value: Any) -> Any:
        if not isinstance(value, MembershipPlan):
            return value
        return {
            "id": value.id,
            "name": value.name,
            "price_minor": value.price_minor,
            "currency": value.currency,
            "duration_days": value.duration_days,
            "booking_window_days": value.booking_window_days,
            "weekly_booking_limit": value.weekly_booking_limit,
            "is_active": value.is_active,
            "entitlements": sorted(entry.entitlement for entry in value.entitlements),
        }


class CreatePlanRequest(BaseModel):
    name: PlanName
    price_minor: int = Field(gt=0, le=MAX_PLAN_PRICE_MINOR)
    currency: CurrencyCode = "EUR"
    duration_days: int = Field(default=30, gt=0, le=MAX_PLAN_DURATION_DAYS)
    booking_window_days: int = Field(ge=0, le=MAX_BOOKING_WINDOW_DAYS)
    weekly_booking_limit: int = Field(ge=0, le=MAX_WEEKLY_BOOKING_LIMIT)
    entitlements: set[MembershipEntitlement] = Field(min_length=1)


class UpdatePlanRequest(BaseModel):
    """Only the fields sent are changed; entitlements, when sent, replace the plan's set."""

    name: PlanName | None = None
    price_minor: int | None = Field(default=None, gt=0, le=MAX_PLAN_PRICE_MINOR)
    currency: CurrencyCode | None = None
    duration_days: int | None = Field(default=None, gt=0, le=MAX_PLAN_DURATION_DAYS)
    booking_window_days: int | None = Field(default=None, ge=0, le=MAX_BOOKING_WINDOW_DAYS)
    weekly_booking_limit: int | None = Field(default=None, ge=0, le=MAX_WEEKLY_BOOKING_LIMIT)
    entitlements: set[MembershipEntitlement] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class PurchaseRequest(BaseModel):
    plan_id: int = Field(gt=0)


class PurchaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership: MembershipResponse
    plan_name: str
    amount_minor: int
    currency: str
    payment_reference: str

    @model_validator(mode="before")
    @classmethod
    def from_purchase_result(cls, value: Any) -> Any:
        if not all(hasattr(value, attribute) for attribute in ("membership", "plan", "payment")):
            return value
        return {
            "membership": value.membership,
            "plan_name": value.plan.name,
            "amount_minor": value.payment.amount_minor,
            "currency": value.payment.currency,
            "payment_reference": value.payment.reference,
        }
