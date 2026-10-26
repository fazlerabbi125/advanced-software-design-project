"""Payment gateway interface and concrete implementations.

Factory Method pattern
-----------------------
``PaymentGatewayFactory.create(settings)`` is the factory method. It reads the
``PAYMENT_PROVIDER`` setting and returns the right concrete gateway. All caller
code only knows about the ``PaymentGateway`` protocol — it never inspects
environment variables or decides which provider to use.

Adding a new provider (e.g. PayPal) means:
  1. Implement ``PaypalGateway`` that satisfies the ``PaymentGateway`` protocol.
  2. Add one ``elif`` branch inside ``PaymentGatewayFactory.create``.
  3. No other files change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.core.config import Settings


class PaymentStatus(StrEnum):
    PENDING = "pending"      # Stripe Checkout session created, awaiting webhook
    APPROVED = "approved"    # Payment confirmed by webhook
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class PaymentResult:
    reference: str           # Stripe Checkout Session ID (cs_test_...)
    status: PaymentStatus
    amount_minor: int
    currency: str
    checkout_url: str | None = None  # Redirect the member here to complete payment


class PaymentGateway(Protocol):
    """Interface every payment provider must satisfy.

    ``charge`` creates a payment session and returns a ``PaymentResult``.
    The result status will be ``PENDING`` for redirect-based flows (Stripe
    Checkout). The membership is only activated after a verified webhook
    event — never based on the browser return URL.
    """

    def charge(self, amount_minor: int, currency: str) -> PaymentResult: ...


class StripeCheckoutGateway:
    """Real Stripe Checkout gateway (sandbox / production depending on key).

    How it works:
    1. ``charge()`` creates a Stripe Checkout Session and returns a PENDING
       result that includes a ``checkout_url``.
    2. The API returns that URL to the client. The member is redirected to
       Stripe's hosted payment page.
    3. After payment, Stripe sends a ``checkout.session.completed`` webhook
       to ``POST /api/v1/payments/stripe/webhook``.
    4. The webhook handler verifies the Stripe-Signature, looks up the
       membership by session ID, and sets its status to ACTIVE.

    The ``MockPaymentGateway`` has been removed. For automated tests, mock
    ``PaymentGatewayFactory.create`` at the dependency-injection level so
    tests never call Stripe's API.
    """

    def __init__(self, secret_key: str, success_url: str, cancel_url: str) -> None:
        import stripe

        self._client = stripe.StripeClient(secret_key)
        self._success_url = success_url
        self._cancel_url = cancel_url

    def charge(self, amount_minor: int, currency: str, plan_name: str = "BFS Gym Membership") -> PaymentResult:  # type: ignore[override]
        import stripe

        session = self._client.checkout.sessions.create(
            params={
                "payment_method_types": ["card"],
                "line_items": [
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {"name": plan_name},
                            "unit_amount": amount_minor,
                        },
                        "quantity": 1,
                    }
                ],
                "mode": "payment",
                "success_url": self._success_url,
                "cancel_url": self._cancel_url,
            }
        )
        return PaymentResult(
            reference=session.id,
            status=PaymentStatus.PENDING,
            amount_minor=amount_minor,
            currency=currency.upper(),
            checkout_url=session.url,
        )


class PaymentGatewayFactory:
    """Factory Method: creates the right payment gateway from application settings.

    The factory is the only place that reads ``PAYMENT_PROVIDER``. Service
    code receives a ``PaymentGateway`` and calls ``.charge()`` — it has no
    knowledge of which provider is behind it.
    """

    @staticmethod
    def create(settings: Settings) -> PaymentGateway:
        # Currently only Stripe is supported. The factory is kept so that
        # future providers (PayPal, GoCardless, etc.) can be plugged in by
        # adding a branch here and a concrete class above.
        return StripeCheckoutGateway(
            secret_key=settings.stripe_secret_key.get_secret_value(),
            success_url=settings.stripe_success_url,
            cancel_url=settings.stripe_cancel_url,
        )
