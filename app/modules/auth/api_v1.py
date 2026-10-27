from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.modules.auth.dependencies import AuthServiceDependency
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: AuthServiceDependency) -> Any:
    try:
        return await service.register(payload.email, payload.password, payload.name, payload.phone)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, service: AuthServiceDependency) -> Any:
    try:
        return await service.login(payload.email, payload.password)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, service: AuthServiceDependency) -> Any:
    try:
        return await service.rotate_refresh_token(payload.refresh_token)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
