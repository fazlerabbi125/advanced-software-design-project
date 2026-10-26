from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.memberships import MembershipEntitlement

PlanName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CurrencyCode = Annotated[str, StringConstraints(to_upper=True, pattern=r"^[A-Za-z]{3}$")]


class MembershipResponse(BaseModel):
    id: int
    plan_id: int
    status: str
    starts_on: date
    ends_on: date


class PlanResponse(BaseModel):
    id: int
    name: str
    price_minor: int
    currency: str
    duration_days: int
    booking_window_days: int
    weekly_booking_limit: int
    is_active: bool
    entitlements: list[str]


class CreatePlanRequest(BaseModel):
    name: PlanName
    price_minor: int = Field(gt=0)
    currency: CurrencyCode = "EUR"
    duration_days: int = Field(default=30, gt=0)
    booking_window_days: int = Field(ge=0)
    weekly_booking_limit: int = Field(ge=0)
    entitlements: set[MembershipEntitlement] = Field(min_length=1)


class UpdatePlanRequest(BaseModel):
    """Only the fields sent are changed; entitlements, when sent, replace the plan's set."""

    name: PlanName | None = None
    price_minor: int | None = Field(default=None, gt=0)
    currency: CurrencyCode | None = None
    duration_days: int | None = Field(default=None, gt=0)
    booking_window_days: int | None = Field(default=None, ge=0)
    weekly_booking_limit: int | None = Field(default=None, ge=0)
    entitlements: set[MembershipEntitlement] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class PurchaseRequest(BaseModel):
    plan_id: int = Field(gt=0)


class PurchaseResponse(BaseModel):
    membership: MembershipResponse
    plan_name: str
    amount_minor: int
    currency: str
    payment_reference: str
