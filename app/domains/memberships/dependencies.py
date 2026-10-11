from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.domains.memberships.service import MembershipService


def get_membership_service(session: DbSession) -> MembershipService:
    return MembershipService(session)


MembershipServiceDependency = Annotated[MembershipService, Depends(get_membership_service)]
