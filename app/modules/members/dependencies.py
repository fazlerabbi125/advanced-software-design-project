from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.modules.members.service import MemberService
from app.storage.biometric_images import BiometricImageStorage


def get_member_service(session: DbSession) -> MemberService:
    return MemberService(session, BiometricImageStorage())


MemberServiceDependency = Annotated[MemberService, Depends(get_member_service)]
