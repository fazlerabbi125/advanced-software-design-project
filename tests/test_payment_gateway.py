"""Stripe Checkout boundary tests.

Set BFS_STRIPE_INTEGRATION_TEST=1 with a test-mode STRIPE_SECRET_KEY to run the
opt-in sandbox test. It creates a Checkout Session but never completes a charge.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.config import Settings
from app.modules.memberships.payment_gateway import (
    PaymentGatewayFactory,
    PaymentStatus,
    StripeCheckoutGateway,
)


class StripeCheckoutGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_dynamic_checkout_session(self) -> None:
        """The gateway sends a valid card Checkout request without invalid wallet types."""
        create_session = AsyncMock(
            return_value=SimpleNamespace(
                id="cs_test_123", url="https://checkout.stripe.test/cs_test_123"
            )
        )
        gateway = object.__new__(StripeCheckoutGateway)
        gateway._client = SimpleNamespace(
            v1=SimpleNamespace(
                checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create_session))
            )
        )
        gateway._success_url = "https://example.test/success"
        gateway._cancel_url = "https://example.test/cancel"

        payment = await gateway.create_checkout(4500, "GBP", plan_name="Premium")

        self.assertEqual(payment.reference, "cs_test_123")
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(payment.checkout_url, "https://checkout.stripe.test/cs_test_123")
        params = create_session.await_args.kwargs["params"]
        self.assertEqual(params["mode"], "payment")
        self.assertEqual(params["line_items"][0]["price_data"]["currency"], "gbp")
        self.assertNotIn("payment_method_types", params)

    @unittest.skipUnless(
        os.getenv("BFS_STRIPE_INTEGRATION_TEST") == "1",
        "set BFS_STRIPE_INTEGRATION_TEST=1 to create a Stripe sandbox Checkout Session",
    )
    async def test_sandbox_creates_checkout_session(self) -> None:
        """Opt-in real Stripe test; it creates a session but does not charge a card."""
        settings = Settings()
        if not settings.stripe_secret_key.get_secret_value().startswith("sk_test_"):
            self.skipTest("STRIPE_SECRET_KEY must be a Stripe test-mode key")
        gateway = PaymentGatewayFactory.create(settings)
        try:
            payment = await gateway.create_checkout(100, "GBP", plan_name="BFS Stripe test")
        finally:
            await gateway.aclose()

        self.assertTrue(payment.reference.startswith("cs_test_"))
        self.assertTrue(payment.checkout_url and payment.checkout_url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
