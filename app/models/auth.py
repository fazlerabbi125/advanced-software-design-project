from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    ASYNC_CASCADE,
    Base,
    IdMixin,
    TimestampMixin,
    enum_values,
)

if TYPE_CHECKING:
    from app.models.access import AccessLog
    from app.models.bookings import Booking, WaitlistEntry
    from app.models.members import MemberProfile
    from app.models.memberships import Membership


class UserRole(StrEnum):
    MEMBER = "member"
    STAFF = "staff"
    MANAGER = "manager"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(sa.String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    role: Mapped[UserRole] = mapped_column(
        sa.Enum(
            UserRole,
            name="user_role",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=UserRole.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    member_profile: Mapped[MemberProfile | None] = relationship(
        back_populates="user",
        cascade=ASYNC_CASCADE,
        passive_deletes=True,
        single_parent=True,
        uselist=False,
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade=ASYNC_CASCADE, passive_deletes=True
    )
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade=ASYNC_CASCADE, passive_deletes=True
    )
    bookings: Mapped[list[Booking]] = relationship(
        back_populates="user", cascade=ASYNC_CASCADE, passive_deletes=True
    )
    waitlist_entries: Mapped[list[WaitlistEntry]] = relationship(
        back_populates="user", cascade=ASYNC_CASCADE, passive_deletes=True
    )
    access_logs: Mapped[list[AccessLog]] = relationship(
        back_populates="user",
        cascade=ASYNC_CASCADE,
        passive_deletes=True,
        foreign_keys="AccessLog.member_id",
    )


class RefreshToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[str] = mapped_column(sa.String(36), unique=True)
    family_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="refresh_tokens")
