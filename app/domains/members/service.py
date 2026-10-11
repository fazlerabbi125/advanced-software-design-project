from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.members import MemberProfile
from app.storage.biometric_images import BiometricImageStorage, UploadStream
from app.utils.helpers import utc_now


class MemberService:
    def __init__(self, session: AsyncSession, storage: BiometricImageStorage) -> None:
        self.session = session
        self.storage = storage

    async def upload_biometric_image(self, user_id: int, upload: UploadStream) -> MemberProfile:
        profile = await self.session.scalar(
            select(MemberProfile).where(MemberProfile.user_id == user_id)
        )
        if profile is None:
            profile = MemberProfile(user_id=user_id)
            self.session.add(profile)
        stored_image = await self.storage.save(user_id, upload)
        profile.biometric_image_key = stored_image.key
        profile.biometric_content_type = stored_image.content_type
        profile.biometric_uploaded_at = utc_now()
        await self.session.commit()
        await self.session.refresh(profile)
        return profile
