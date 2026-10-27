from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.auth import UserRole
from app.shared.constants import MIN_PASSWORD_LENGTH


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    created_at: datetime


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
