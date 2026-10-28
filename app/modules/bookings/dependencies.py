from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSessionDep
from app.modules.bookings.service import BookingService
from app.modules.memberships.dependencies import MembershipServiceDependency
from app.modules.notifications.dependencies import NotificationObserverDependency


def get_booking_service(
    session: DbSessionDep,
    memberships: MembershipServiceDependency,
    notifications: NotificationObserverDependency,
) -> BookingService:
    return BookingService(session, memberships, notifications)


BookingServiceDependency = Annotated[BookingService, Depends(get_booking_service)]
