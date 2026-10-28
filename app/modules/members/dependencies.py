from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSessionDep
from app.modules.members.photo_validation import get_photo_validator
from app.modules.members.service import MemberService
from app.storage.biometric_images import BiometricImageStorage


def get_member_service(session: DbSessionDep) -> MemberService:
    return MemberService(session, BiometricImageStorage(get_photo_validator()))


MemberServiceDependency = Annotated[MemberService, Depends(get_member_service)]
