from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.modules.auth.dependencies import CurrentUser
from app.modules.members.dependencies import MemberServiceDependency
from app.modules.members.schemas import BiometricImageResponse

router = APIRouter(prefix="/members", tags=["members"])


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
            image,
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
