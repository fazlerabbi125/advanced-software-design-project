from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.auth import RefreshToken, User, UserRole
from app.models.members import MemberProfile
from app.shared.constants import MIN_PASSWORD_LENGTH
from app.shared.helpers import normalize_email, utc_now


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


class AuthService:
    async def register(
        self, session: AsyncSession, email: str, password: str, name: str, phone: str | None
    ) -> User:
        normalized_email = normalize_email(email)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AppError("password does not meet the minimum length", 422)
        name = name.strip()
        if not name:
            raise AppError("name is required", 422)
        existing_user = await session.scalar(select(User).where(User.email == normalized_email))
        if existing_user is not None:
            raise AppError("email is already registered", 409)
        user = User(
            email=normalized_email, password_hash=hash_password(password), role=UserRole.MEMBER
        )
        user.member_profile = MemberProfile(name=name, phone=phone)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as error:
            # The database constraint closes the race between the earlier lookup and insert.
            raise AppError("email is already registered", 409) from error
        return user

    async def get_user_by_id(self, session: AsyncSession, user_id: str | UUID) -> User | None:
        try:
            return await session.get(User, UUID(str(user_id)))
        except ValueError:
            return None

    async def login(self, session: AsyncSession, email: str, password: str) -> TokenPair:
        user = await session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AppError("invalid email or password", 401)
        return await self._issue_tokens(session, user)

    async def rotate_refresh_token(self, session: AsyncSession, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, "refresh")
        try:
            jti = payload["jti"]
            user_id = UUID(payload["sub"])
        except (KeyError, ValueError) as error:
            raise AppError("invalid refresh token", 401) from error
        token_record = await session.scalar(
            select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()
        )
        if (
            token_record is None
            or token_record.revoked_at is not None
            or token_record.expires_at <= utc_now()
        ):
            raise AppError("refresh token is no longer valid", 401)
        if token_record.user_id != user_id:
            raise AppError("refresh token is no longer valid", 401)
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            raise AppError("user is not active", 401)
        token_record.revoked_at = utc_now()
        return await self._issue_tokens(session, user, token_record.family_id)

    async def _issue_tokens(
        self, session: AsyncSession, user: User, family_id: str | None = None
    ) -> TokenPair:
        refresh_token, jti, resolved_family_id, expires_at = create_refresh_token(
            user.id, family_id
        )
        session.add(
            RefreshToken(
                user_id=user.id,
                jti=jti,
                family_id=resolved_family_id,
                expires_at=expires_at,
            )
        )
        await session.flush()
        return TokenPair(
            access_token=create_access_token(user.id, user.role.value),
            refresh_token=refresh_token,
        )
