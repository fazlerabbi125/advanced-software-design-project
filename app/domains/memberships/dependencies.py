from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.domains.memberships.payment_gateway import MockPaymentGateway, PaymentGateway
from app.domains.memberships.service import MembershipService


def get_payment_gateway() -> PaymentGateway:
    return MockPaymentGateway()


PaymentGatewayDependency = Annotated[PaymentGateway, Depends(get_payment_gateway)]


def get_membership_service(
    session: DbSession, payment_gateway: PaymentGatewayDependency
) -> MembershipService:
    return MembershipService(session, payment_gateway)


MembershipServiceDependency = Annotated[MembershipService, Depends(get_membership_service)]
