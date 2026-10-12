from dataclasses import dataclass
from enum import StrEnum
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


class MockPaymentGateway:
    def __init__(self, approve_payments: bool = True) -> None:
        self.approve_payments = approve_payments

    def charge(self, amount_minor: int, currency: str = "GBP") -> PaymentResult:
        if amount_minor <= 0:
            raise ValueError("Payment amount must be positive")

        status = PaymentStatus.APPROVED if self.approve_payments else PaymentStatus.DECLINED
        return PaymentResult(
            reference=f"mock_{uuid4().hex}",
            status=status,
            amount_minor=amount_minor,
            currency=currency.upper(),
        )
