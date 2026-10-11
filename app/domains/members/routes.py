from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.dependencies import CurrentUser
from app.domains.members.dependencies import MemberServiceDependency

router = APIRouter(prefix="/members", tags=["members"])


class BiometricImageResponse(BaseModel):
    image_key: str
    content_type: str
    uploaded_at: datetime


@router.post(
    "/me/biometric-image",
    response_model=BiometricImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_biometric_image(
    current_user: CurrentUser,
    service: MemberServiceDependency,
    image: Annotated[UploadFile, File()],
) -> BiometricImageResponse:
    try:
        profile = await service.upload_biometric_image(
            current_user.id,
            image.filename or "biometric-image",
            image.content_type or "",
            await image.read(),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return BiometricImageResponse(
        image_key=profile.biometric_image_key or "",
        content_type=profile.biometric_content_type or "",
        uploaded_at=profile.biometric_uploaded_at or profile.created_at,
    )
