from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.domains.auth.dependencies import AuthServiceDependency
from app.domains.auth.service import TokenPair
from app.models.auth import User
from app.utils.constants import MIN_PASSWORD_LENGTH

router = APIRouter(prefix="/auth", tags=["auth"])


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


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, role=user.role.value, created_at=user.created_at
    )


def token_response(tokens: TokenPair) -> TokenResponse:
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: AuthServiceDependency) -> UserResponse:
    try:
        return user_response(await service.register(payload.email, payload.password))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, service: AuthServiceDependency) -> TokenResponse:
    try:
        return token_response(await service.login(payload.email, payload.password))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, service: AuthServiceDependency) -> TokenResponse:
    try:
        return token_response(await service.rotate_refresh_token(payload.refresh_token))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
