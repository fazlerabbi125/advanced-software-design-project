from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSessionDep
from app.modules.bookings.service import BookingService
from app.modules.memberships.dependencies import MembershipServiceDependency


def get_booking_service(
    session: DbSessionDep, memberships: MembershipServiceDependency
) -> BookingService:
    return BookingService(session, memberships)


BookingServiceDependency = Annotated[BookingService, Depends(get_booking_service)]
