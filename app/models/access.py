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


class DeniedAccessReason(enum.StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN_TEMPLATE = "unknown_template"
    ACCESS_DENIED = "access_denied"
    ZONE_FULL = "zone_full"


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
    # Set only for manual check-ins: the staff member who let the member in, and why.
    performed_by_staff_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    staff_reason: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="access_logs", foreign_keys=[member_id])


class DeniedAccessAttempt(IdMixin, TimestampMixin, Base):
    """A scanner rejection, including attempts that cannot be linked to a member."""

    __tablename__ = "denied_access_attempts"

    biometric_template_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    scanner_key_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    zone: Mapped[AccessZone] = mapped_column(
        Enum(
            AccessZone,
            name="access_zone",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    confidence: Mapped[float] = mapped_column()
    reason: Mapped[DeniedAccessReason] = mapped_column(
        Enum(
            DeniedAccessReason,
            name="denied_access_reason",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
