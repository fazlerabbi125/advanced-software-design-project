from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import User


class AccessEvent(enum.StrEnum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    MANUAL_CHECK_IN = "manual_check_in"


class AccessLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "access_logs"

    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event: Mapped[AccessEvent] = mapped_column(
        Enum(AccessEvent, name="access_event", native_enum=False, create_constraint=True)
    )
    zone: Mapped[str] = mapped_column(String(100), default="gym_floor")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(50), default="biometric")

    user: Mapped[User] = relationship(back_populates="access_logs")
