from typing import Annotated

from fastapi import Depends

from app.modules.bookings.service import BookingService
from app.modules.memberships.dependencies import MembershipServiceDep
from app.modules.notifications.dependencies import NotificationObserverDep


def get_booking_service(
    memberships: MembershipServiceDep,
    notifications: NotificationObserverDep,
) -> BookingService:
    return BookingService(memberships, notifications)


BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
