from typing import Annotated

from fastapi import Depends

from app.modules.members.photo_validation import get_photo_validator
from app.modules.members.service import MemberService
from app.storage.biometric_images import BiometricImageStorage


def get_member_service() -> MemberService:
    return MemberService(BiometricImageStorage(get_photo_validator()))


MemberServiceDep = Annotated[MemberService, Depends(get_member_service)]
