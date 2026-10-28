from typing import Annotated

from fastapi import Depends, Request

from app.core.dependencies import DbSession
from app.modules.memberships.payment_gateway import PaymentGateway
from app.modules.memberships.service import MembershipService


def get_payment_gateway(request: Request) -> PaymentGateway:
    return request.app.state.payment_gateway


PaymentGatewayDependency = Annotated[PaymentGateway, Depends(get_payment_gateway)]


def get_membership_service(
    session: DbSession, payment_gateway: PaymentGatewayDependency
) -> MembershipService:
    return MembershipService(session, payment_gateway)


MembershipServiceDependency = Annotated[MembershipService, Depends(get_membership_service)]
