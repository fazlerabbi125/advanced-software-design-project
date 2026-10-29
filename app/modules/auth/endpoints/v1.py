from typing import Any

from fastapi import APIRouter, status

from app.core.dependencies import DbSessionDep
from app.core.exceptions import AppError, http_error
from app.modules.auth.dependencies import AuthServiceDependency
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    description="Register a member account.",
)
async def register(
    payload: RegisterRequest, session: DbSessionDep, service: AuthServiceDependency
) -> Any:
    try:
        user = await service.register(
            session, payload.email, payload.password, payload.name, payload.phone
        )
        await session.commit()
        return user
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise


@router.post("/login", response_model=TokenResponse, description="Sign in and issue JWT tokens.")
async def login(
    payload: LoginRequest, session: DbSessionDep, service: AuthServiceDependency
) -> Any:
    try:
        tokens = await service.login(session, payload.email, payload.password)
        await session.commit()
        return tokens
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise


@router.post("/refresh", response_model=TokenResponse, description="Rotate a refresh token.")
async def refresh(
    payload: RefreshRequest, session: DbSessionDep, service: AuthServiceDependency
) -> Any:
    try:
        tokens = await service.rotate_refresh_token(session, payload.refresh_token)
        await session.commit()
        return tokens
    except AppError as error:
        await session.rollback()
        raise http_error(error) from error
    except Exception:
        await session.rollback()
        raise
