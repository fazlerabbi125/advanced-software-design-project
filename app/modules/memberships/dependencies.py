from typing import Annotated

from fastapi import Depends, Request

from app.core.dependencies import DbSessionDep
from app.modules.memberships.payment_gateway import PaymentGateway
from app.modules.memberships.service import MembershipService
from app.modules.notifications.dependencies import NotificationObserverDependency


def get_payment_gateway(request: Request) -> PaymentGateway:
    return request.app.state.payment_gateway


PaymentGatewayDependency = Annotated[PaymentGateway, Depends(get_payment_gateway)]


def get_membership_service(
    session: DbSessionDep,
    payment_gateway: PaymentGatewayDependency,
    notifications: NotificationObserverDependency,
) -> MembershipService:
    return MembershipService(session, payment_gateway, notifications)


MembershipServiceDependency = Annotated[MembershipService, Depends(get_membership_service)]
