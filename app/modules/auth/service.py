from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register(self, email: str, password: str, name: str, phone: str | None) -> User:
        normalized_email = normalize_email(email)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError("password does not meet the minimum length")
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        existing_user = await self.session.scalar(
            select(User).where(User.email == normalized_email)
        )
        if existing_user is not None:
            raise ValueError("email is already registered")
        user = User(
            email=normalized_email, password_hash=hash_password(password), role=UserRole.MEMBER
        )
        user.member_profile = MemberProfile(name=name, phone=phone)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_user_by_id(self, user_id: str | UUID) -> User | None:
        try:
            return await self.session.get(User, UUID(str(user_id)))
        except ValueError:
            return None

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise ValueError("invalid email or password")
        return await self._issue_tokens(user)

    async def rotate_refresh_token(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, "refresh")
        try:
            jti = payload["jti"]
            user_id = UUID(payload["sub"])
        except (KeyError, ValueError) as error:
            raise ValueError("invalid refresh token") from error
        token_record = await self.session.scalar(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )
        if (
            token_record is None
            or token_record.revoked_at is not None
            or token_record.expires_at <= utc_now()
        ):
            raise ValueError("refresh token is no longer valid")
        if token_record.user_id != user_id:
            raise ValueError("refresh token is no longer valid")
        user = await self.session.get(User, user_id)
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
