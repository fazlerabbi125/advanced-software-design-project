from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.members import MemberProfile
from app.shared.helpers import utc_now
from app.storage.biometric_images import BiometricImageStorage, UploadStream


class MemberService:
    def __init__(self, session: AsyncSession, storage: BiometricImageStorage) -> None:
        self.session = session
        self.storage = storage

    async def upload_biometric_image(self, user_id: UUID, upload: UploadStream) -> MemberProfile:
        profile = await self.session.scalar(
            select(MemberProfile).where(MemberProfile.user_id == user_id)
        )
        if profile is None:
            raise ValueError("member profile does not exist")
        stored_image = await self.storage.save(user_id, upload)
        profile.biometric_image_key = stored_image.key
        profile.biometric_content_type = stored_image.content_type
        profile.biometric_uploaded_at = utc_now()
        await self.session.commit()
        await self.session.refresh(profile)
        return profile
