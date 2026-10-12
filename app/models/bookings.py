from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import User


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BookingResourceType(StrEnum):
    CLASS = "class"
    POOL = "pool"
    PERSONAL_TRAINING = "personal_training"


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class Booking(Base, IdMixin, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (sa.UniqueConstraint("user_id", "resource_name", "starts_at"),)

    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    resource_name: Mapped[str] = mapped_column(sa.String(150), index=True)
    resource_type: Mapped[BookingResourceType] = mapped_column(
        sa.Enum(
            BookingResourceType,
            name="booking_resource_type",
            native_enum=False,
            create_constraint=True,
        )
    )
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    status: Mapped[BookingStatus] = mapped_column(
        sa.Enum(BookingStatus, name="booking_status", native_enum=False, create_constraint=True),
        default=BookingStatus.CONFIRMED,
    )
    user: Mapped[User] = relationship(back_populates="bookings")
    waitlist_entries: Mapped[list[WaitlistEntry]] = relationship(back_populates="booking")


class WaitlistEntry(Base, IdMixin, TimestampMixin):
    __tablename__ = "waitlist_entries"
    __table_args__ = (sa.UniqueConstraint("booking_id", "user_id"),)

    booking_id: Mapped[int] = mapped_column(
        sa.ForeignKey("bookings.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[WaitlistStatus] = mapped_column(
        sa.Enum(WaitlistStatus, name="waitlist_status", native_enum=False, create_constraint=True),
        default=WaitlistStatus.WAITING,
    )
    offered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    booking: Mapped[Booking] = relationship(back_populates="waitlist_entries")
