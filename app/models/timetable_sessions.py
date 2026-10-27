from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, enum_values
from app.models.bookings import BookingResourceType

if TYPE_CHECKING:
    from app.models.bookings import Booking, WaitlistEntry


class TimetableSession(Base, IdMixin, TimestampMixin):
    """A scheduled class, pool lane block or personal training slot on the timetable.

    Named TimetableSession rather than Session so it is not confused with the
    SQLAlchemy database session used everywhere in the services.
    """

    __tablename__ = "timetable_sessions"
    __table_args__ = (
        sa.CheckConstraint("capacity > 0", name="ck_timetable_sessions_capacity_positive"),
        sa.CheckConstraint(
            "allocated_count >= 0 AND allocated_count <= capacity",
            name="ck_timetable_sessions_allocated_within_capacity",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_timetable_sessions_ends_after_start"),
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
    ends_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(sa.Integer)
    allocated_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    station_count: Mapped[int | None] = mapped_column(sa.Integer)
    bookings: Mapped[list[Booking]] = relationship(back_populates="session")
    waitlist_entries: Mapped[list[WaitlistEntry]] = relationship(back_populates="session")

    @property
    def spots_left(self) -> int:
        return self.capacity - self.allocated_count

    @property
    def is_full(self) -> bool:
        return self.allocated_count >= self.capacity
