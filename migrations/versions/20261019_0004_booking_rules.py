"""Store booking limits on plans so new plans do not require new rule classes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_0004"
down_revision: str | None = "20261012_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "membership_plans",
        sa.Column("booking_window_days", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("weekly_booking_limit", sa.Integer(), nullable=False, server_default="3"),
    )
    op.execute(
        "UPDATE membership_plans SET booking_window_days = 3, weekly_booking_limit = 5 "
        "WHERE lower(name) = 'standard'"
    )
    op.execute(
        "UPDATE membership_plans SET booking_window_days = 7, weekly_booking_limit = 10 "
        "WHERE lower(name) = 'premium'"
    )
    op.create_check_constraint(
        "booking_window_nonnegative", "membership_plans", "booking_window_days >= 0"
    )
    op.create_check_constraint(
        "weekly_limit_nonnegative", "membership_plans", "weekly_booking_limit >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("weekly_limit_nonnegative", "membership_plans", type_="check")
    op.drop_constraint("booking_window_nonnegative", "membership_plans", type_="check")
    op.drop_column("membership_plans", "weekly_booking_limit")
    op.drop_column("membership_plans", "booking_window_days")
