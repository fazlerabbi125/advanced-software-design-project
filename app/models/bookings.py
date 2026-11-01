from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, enum_values

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.timetable_sessions import TimetableSession


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    CHECKED_IN = "checked_in"
    NO_SHOW = "no_show"


class BookingResourceType(StrEnum):
    CLASS = "class"
    POOL = "pool"
    PERSONAL_TRAINING = "personal_training"
    EQUIPMENT = "equipment"


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class Booking(Base, IdMixin, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (sa.UniqueConstraint("user_id", "resource_name", "starts_at"),)

    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    resource_name: Mapped[str] = mapped_column(sa.String(150), index=True)
    resource_type: Mapped[BookingResourceType] = mapped_column(
        sa.Enum(
            BookingResourceType,
            name="booking_resource_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    timetable_session_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("timetable_sessions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[BookingStatus] = mapped_column(
        sa.Enum(
            BookingStatus,
            name="booking_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=BookingStatus.CONFIRMED,
    )
    user: Mapped[User] = relationship(back_populates="bookings")
    session: Mapped[TimetableSession | None] = relationship(back_populates="bookings")


class WaitlistEntry(Base, IdMixin, TimestampMixin):
    __tablename__ = "waitlist_entries"
    __table_args__ = (sa.UniqueConstraint("session_id", "user_id"),)

    session_id: Mapped[int] = mapped_column(
        sa.ForeignKey("timetable_sessions.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[WaitlistStatus] = mapped_column(
        sa.Enum(
            WaitlistStatus,
            name="waitlist_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=WaitlistStatus.WAITING,
    )
    offered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    session: Mapped[TimetableSession] = relationship(back_populates="waitlist_entries")
    user: Mapped[User] = relationship(back_populates="waitlist_entries")
