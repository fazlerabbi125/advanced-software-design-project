from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.domains.bookings.service import BookingService


def get_booking_service(session: DbSession) -> BookingService:
    return BookingService(session)


BookingServiceDependency = Annotated[BookingService, Depends(get_booking_service)]
