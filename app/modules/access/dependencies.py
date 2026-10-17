from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.modules.access.service import AccessService


def get_access_service(session: DbSession) -> AccessService:
    return AccessService(session)


AccessServiceDependency = Annotated[AccessService, Depends(get_access_service)]
