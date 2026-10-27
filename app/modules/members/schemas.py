from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.members import MemberProfile


class BiometricImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    image_key: str
    content_type: str
    uploaded_at: datetime

    @model_validator(mode="before")
    @classmethod
    def from_member_profile(cls, value: Any) -> Any:
        if not isinstance(value, MemberProfile):
            return value
        return {
            "image_key": value.biometric_image_key or "",
            "content_type": value.biometric_content_type or "",
            "uploaded_at": value.biometric_uploaded_at or value.created_at,
        }
