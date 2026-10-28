from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.dependencies import DbSessionDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.members.dependencies import MemberServiceDependency
from app.modules.members.schemas import BiometricImageResponse

router = APIRouter(prefix="/members", tags=["members"])


@router.post(
    "/me/biometric-image",
    response_model=BiometricImageResponse,
    status_code=status.HTTP_201_CREATED,
    description="Upload your biometric enrolment image.",
)
async def upload_biometric_image(
    current_user: CurrentUser,
    session: DbSessionDep,
    service: MemberServiceDependency,
    image: Annotated[UploadFile, File()],
) -> Any:
    try:
        profile = await service.upload_biometric_image(
            current_user.id,
            image,
        )
        await session.commit()
    except ValueError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception:
        await session.rollback()
        raise
    return profile
