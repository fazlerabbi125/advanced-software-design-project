from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import User


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MembershipEntitlement(StrEnum):
    GYM_FLOOR_ACCESS = "gym_floor_access"
    CLASS_BOOKING = "class_booking"
    POOL_BOOKING = "pool_booking"
    REFRESHMENTS = "refreshments"
    PERSONAL_TRAINING = "personal_training"
    TRAINING_PLANS = "training_plans"
    VIP_AREA_ACCESS = "vip_area_access"


class MembershipPlan(Base, IdMixin, TimestampMixin):
    __tablename__ = "membership_plans"
    __table_args__ = (
        sa.CheckConstraint("booking_window_days >= 0", name="booking_window_nonnegative"),
        sa.CheckConstraint("weekly_booking_limit >= 0", name="weekly_limit_nonnegative"),
    )

    name: Mapped[str] = mapped_column(sa.String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    price_minor: Mapped[int] = mapped_column(sa.Integer)
    currency: Mapped[str] = mapped_column(sa.String(3), default="EUR", server_default="EUR")
    duration_days: Mapped[int] = mapped_column(default=30, server_default="30")
    booking_window_days: Mapped[int] = mapped_column(default=2, server_default="2")
    weekly_booking_limit: Mapped[int] = mapped_column(default=3, server_default="3")
    memberships: Mapped[list[Membership]] = relationship(back_populates="plan")
    entitlements: Mapped[list[PlanEntitlement]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanEntitlement(Base, IdMixin, TimestampMixin):
    __tablename__ = "plan_entitlements"
    __table_args__ = (sa.UniqueConstraint("plan_id", "entitlement"),)

    plan_id: Mapped[int] = mapped_column(
        sa.ForeignKey("membership_plans.id", ondelete="CASCADE"), index=True
    )
    entitlement: Mapped[MembershipEntitlement] = mapped_column(
        sa.Enum(
            MembershipEntitlement,
            name="membership_entitlement",
            native_enum=False,
            create_constraint=True,
        )
    )
    plan: Mapped[MembershipPlan] = relationship(back_populates="entitlements")


class Membership(Base, IdMixin, TimestampMixin):
    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    plan_id: Mapped[int] = mapped_column(sa.ForeignKey("membership_plans.id", ondelete="RESTRICT"))
    status: Mapped[MembershipStatus] = mapped_column(
        sa.Enum(
            MembershipStatus, name="membership_status", native_enum=False, create_constraint=True
        ),
        default=MembershipStatus.ACTIVE,
    )
    starts_on: Mapped[date] = mapped_column(sa.Date)
    ends_on: Mapped[date] = mapped_column(sa.Date, index=True)
    payment_reference: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    user: Mapped[User] = relationship(back_populates="memberships")
    plan: Mapped[MembershipPlan] = relationship(back_populates="memberships")
