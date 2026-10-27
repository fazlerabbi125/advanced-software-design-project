from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.models.auth import User, UserRole
from app.modules.auth.dependencies import require_roles
from app.modules.bookings.outages import UnitOutageHandler
from app.modules.facilities.service import FacilitiesService


def get_facilities_service(session: DbSession) -> FacilitiesService:
    return FacilitiesService(session)


def get_outage_handler(session: DbSession) -> UnitOutageHandler:
    return UnitOutageHandler(session)


FacilitiesServiceDependency = Annotated[FacilitiesService, Depends(get_facilities_service)]
# Shares the request's database session with FacilitiesService, so confirming a fault and
# moving or cancelling the unit's slots commit together.
OutageHandlerDependency = Annotated[UnitOutageHandler, Depends(get_outage_handler)]
StaffUser = Annotated[User, Depends(require_roles(UserRole.STAFF, UserRole.MANAGER))]
