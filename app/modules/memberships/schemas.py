from datetime import date

from pydantic import BaseModel, Field


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
    entitlements: list[str]


class PurchaseRequest(BaseModel):
    plan_id: int = Field(gt=0)


class PurchaseResponse(BaseModel):
    membership: MembershipResponse
    plan_name: str
    amount_minor: int
    currency: str
    payment_reference: str
