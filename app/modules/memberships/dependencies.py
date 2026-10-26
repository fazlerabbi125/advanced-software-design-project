from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.dependencies import DbSession
from app.modules.memberships.payment_gateway import PaymentGateway, PaymentGatewayFactory
from app.modules.memberships.service import MembershipService


def get_payment_gateway(settings: Annotated[Settings, Depends(get_settings)]) -> PaymentGateway:
    """FastAPI dependency: use PaymentGatewayFactory to get the configured gateway.

    The factory reads ``settings.stripe_secret_key`` and returns a
    ``StripeCheckoutGateway``. Service code only sees the ``PaymentGateway``
    protocol — it never inspects settings itself.
    """
    return PaymentGatewayFactory.create(settings)


PaymentGatewayDependency = Annotated[PaymentGateway, Depends(get_payment_gateway)]


def get_membership_service(
    session: DbSession, payment_gateway: PaymentGatewayDependency
) -> MembershipService:
    return MembershipService(session, payment_gateway)


MembershipServiceDependency = Annotated[MembershipService, Depends(get_membership_service)]
