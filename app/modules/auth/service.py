from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.auth import RefreshToken, User, UserRole
from app.utils.constants import MIN_PASSWORD_LENGTH
from app.utils.helpers import normalize_email, utc_now


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register(self, email: str, password: str) -> User:
        normalized_email = normalize_email(email)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError("password does not meet the minimum length")
        existing_user = await self.session.scalar(
            select(User).where(User.email == normalized_email)
        )
        if existing_user is not None:
            raise ValueError("email is already registered")
        user = User(
            email=normalized_email, password_hash=hash_password(password), role=UserRole.MEMBER
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_user_by_id(self, user_id: str | int) -> User | None:
        return await self.session.get(User, int(user_id))

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise ValueError("invalid email or password")
        return await self._issue_tokens(user)

    async def rotate_refresh_token(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, "refresh")
        token_record = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(refresh_token),
                RefreshToken.jti == payload["jti"],
            )
        )
        if (
            token_record is None
            or token_record.revoked_at is not None
            or token_record.expires_at <= utc_now()
        ):
            raise ValueError("refresh token is no longer valid")
        user = await self.session.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            raise ValueError("user is not active")
        token_record.revoked_at = utc_now()
        return await self._issue_tokens(user, token_record.family_id)

    async def _issue_tokens(self, user: User, family_id: str | None = None) -> TokenPair:
        refresh_token, jti, resolved_family_id, expires_at = create_refresh_token(
            user.id, family_id
        )
        self.session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh_token),
                jti=jti,
                family_id=resolved_family_id,
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        return TokenPair(
            access_token=create_access_token(user.id, user.role.value),
            refresh_token=refresh_token,
        )
