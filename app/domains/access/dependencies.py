from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.access.service import AccessService


def get_access_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> AccessService:
    return AccessService(session)


AccessServiceDependency = Annotated[AccessService, Depends(get_access_service)]
