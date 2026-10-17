from datetime import datetime

from pydantic import BaseModel, Field

from app.utils.constants import MIN_PASSWORD_LENGTH


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


class LoginRequest(RegisterRequest):
    pass


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
