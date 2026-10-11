from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.members import MemberProfile
from app.storage.biometric_images import BiometricImageStorage
from app.utils.helpers import utc_now


class MemberService:
    def __init__(self, session: AsyncSession, storage: BiometricImageStorage) -> None:
        self.session = session
        self.storage = storage

    async def upload_biometric_image(
        self, user_id: int, filename: str, content_type: str, content: bytes
    ) -> MemberProfile:
        profile = await self.session.scalar(
            select(MemberProfile).where(MemberProfile.user_id == user_id)
        )
        if profile is None:
            profile = MemberProfile(user_id=user_id)
            self.session.add(profile)
        profile.biometric_image_key = await self.storage.save(
            user_id, filename, content_type, content
        )
        profile.biometric_content_type = content_type
        profile.biometric_uploaded_at = utc_now()
        await self.session.commit()
        await self.session.refresh(profile)
        return profile
