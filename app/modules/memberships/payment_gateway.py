from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import uuid4


class PaymentStatus(StrEnum):
    APPROVED = "approved"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class PaymentResult:
    reference: str
    status: PaymentStatus
    amount_minor: int
    currency: str


class PaymentGateway(Protocol):
    """Interface every payment provider must satisfy (mock now, a real provider later)."""

    def charge(self, amount_minor: int, currency: str) -> PaymentResult: ...


class MockPaymentGateway:
    def __init__(self, approve_payments: bool = True) -> None:
        self.approve_payments = approve_payments

    def charge(self, amount_minor: int, currency: str = "EUR") -> PaymentResult:
        if amount_minor <= 0:
            raise ValueError("Payment amount must be positive")

        status = PaymentStatus.APPROVED if self.approve_payments else PaymentStatus.DECLINED
        return PaymentResult(
            reference=f"mock_{uuid4().hex}",
            status=status,
            amount_minor=amount_minor,
            currency=currency.upper(),
        )
