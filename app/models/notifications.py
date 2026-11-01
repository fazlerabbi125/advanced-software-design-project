from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, enum_values

if TYPE_CHECKING:
    from app.models.auth import User


class NotificationType(StrEnum):
    BOOKING_CONFIRMED = "booking.confirmed"
    BOOKING_CANCELLED = "booking.cancelled"
    WAITLIST_OFFER_CREATED = "waitlist.offer_created"
    MEMBERSHIP_PAYMENT_CONFIRMED = "membership.payment_confirmed"
    MEMBERSHIP_CANCELLED = "membership.cancelled"
    MEMBERSHIP_RENEWED = "membership.renewed"


class Notification(Base, IdMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        sa.Index("ix_notifications_user_unread_created", "user_id", "is_read", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[NotificationType] = mapped_column(
        sa.Enum(
            NotificationType,
            name="notification_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    is_read: Mapped[bool] = mapped_column(default=False, server_default=sa.false(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="notifications")
