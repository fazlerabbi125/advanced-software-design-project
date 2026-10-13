from fastapi import APIRouter, HTTPException, status

from app.models.auth import User
from app.modules.auth.dependencies import AuthServiceDependency
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.modules.auth.service import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


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
