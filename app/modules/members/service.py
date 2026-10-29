from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.members import MemberProfile
from app.shared.helpers import utc_now
from app.storage.biometric_images import BiometricImageStorage, UploadStream


class MemberService:
    def __init__(self, storage: BiometricImageStorage) -> None:
        self.storage = storage

    async def upload_biometric_image(
        self, session: AsyncSession, user_id: UUID, upload: UploadStream
    ) -> MemberProfile:
        profile = await session.scalar(
            select(MemberProfile).where(MemberProfile.user_id == user_id)
        )
        if profile is None:
            raise AppError("member profile does not exist", 404)
        try:
            stored_image = await self.storage.save(user_id, upload)
        except ValueError as error:
            raise AppError(str(error), 422) from error
        profile.biometric_image_key = stored_image.key
        profile.biometric_content_type = stored_image.content_type
        profile.biometric_uploaded_at = utc_now()
        await session.flush()
        return profile
