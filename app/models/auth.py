from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.access import AccessLog
    from app.models.bookings import Booking
    from app.models.members import MemberProfile
    from app.models.memberships import Membership


class UserRole(StrEnum):
    MEMBER = "member"
    STAFF = "staff"
    MANAGER = "manager"


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    role: Mapped[UserRole] = mapped_column(
        sa.Enum(UserRole, name="user_role", native_enum=False, create_constraint=True),
        default=UserRole.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    member_profile: Mapped[MemberProfile | None] = relationship(
        back_populates="user", cascade="save-update, merge, delete, delete-orphan", uselist=False
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    memberships: Mapped[list[Membership]] = relationship(back_populates="user")
    bookings: Mapped[list[Booking]] = relationship(back_populates="user")
    access_logs: Mapped[list[AccessLog]] = relationship(back_populates="user")


class RefreshToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    jti: Mapped[str] = mapped_column(sa.String(36), unique=True)
    family_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="refresh_tokens")
