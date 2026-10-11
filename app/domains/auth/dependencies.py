from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.auth.service import AuthService


def get_auth_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> AuthService:
    return AuthService(session)


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
