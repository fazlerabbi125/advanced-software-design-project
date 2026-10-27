from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, enum_values

if TYPE_CHECKING:
    from app.models.auth import User


class AccessEvent(enum.StrEnum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    MANUAL_CHECK_IN = "manual_check_in"


class AccessZone(enum.StrEnum):
    GYM_FLOOR = "gym_floor"
    VIP_SAUNA = "vip_sauna"
    VIP_MASSAGE = "vip_massage"
    VIP_COLD_PLUNGE = "vip_cold_plunge"


class AccessLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "access_logs"

    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[AccessEvent] = mapped_column(
        Enum(
            AccessEvent,
            name="access_event",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    zone: Mapped[str] = mapped_column(String(150), default=AccessZone.GYM_FLOOR.value)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(50), default="biometric")

    user: Mapped[User] = relationship(back_populates="access_logs")
