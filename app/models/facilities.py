from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, enum_values


class FaultStatus(enum.StrEnum):
    REPORTED = "reported"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class EquipmentUnit(Base, IdMixin, TimestampMixin):
    """A registered piece of bookable equipment, such as Squat Rack 2."""

    __tablename__ = "equipment_units"
    __table_args__ = (sa.Index("uq_equipment_units_name_ci", sa.text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(sa.String(150))
    # Units of the same type can stand in for each other when one leaves service.
    equipment_type: Mapped[str] = mapped_column(sa.String(50), index=True)
    zone: Mapped[str] = mapped_column(sa.String(100), default="gym_floor")
    in_service: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    faults: Mapped[list[EquipmentFault]] = relationship(back_populates="unit")


class EquipmentFault(Base, IdMixin, TimestampMixin):
    """A fault a member or staff member reported on a unit, and what staff decided."""

    __tablename__ = "equipment_faults"

    unit_id: Mapped[int] = mapped_column(
        sa.ForeignKey("equipment_units.id", ondelete="RESTRICT"), index=True
    )
    reported_by_id: Mapped[UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str] = mapped_column(sa.String(1000))
    status: Mapped[FaultStatus] = mapped_column(
        sa.Enum(
            FaultStatus,
            name="equipment_fault_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=FaultStatus.REPORTED,
        index=True,
    )
    # The staff member who confirmed or dismissed the report, and when.
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    unit: Mapped[EquipmentUnit] = relationship(back_populates="faults")
