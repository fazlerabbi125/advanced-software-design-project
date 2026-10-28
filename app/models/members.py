from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import User


class MemberProfile(Base, IdMixin, TimestampMixin):
    __tablename__ = "member_profiles"

    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    phone: Mapped[str | None] = mapped_column(sa.String(30))
    date_of_birth: Mapped[date | None] = mapped_column(sa.Date)
    biometric_template_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), default=uuid4, unique=True
    )
    biometric_image_key: Mapped[str | None] = mapped_column(sa.String(512), unique=True)
    biometric_content_type: Mapped[str | None] = mapped_column(sa.String(100))
    biometric_uploaded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="member_profile", single_parent=True)
