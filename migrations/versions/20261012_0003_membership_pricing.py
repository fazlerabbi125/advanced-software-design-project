from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_0003"
down_revision: str | None = "20261012_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Monthly prices in cent (minor units), so EUR 30.00 is stored as 3000.
PLAN_PRICES = {"basic": 3000, "standard": 4500, "premium": 7000}


def upgrade() -> None:
    op.add_column(
        "membership_plans",
        sa.Column("price_minor", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="30"),
    )
    for name, price_minor in PLAN_PRICES.items():
        op.execute(
            sa.text(
                "UPDATE membership_plans SET price_minor = :price WHERE lower(name) = :name"
            ).bindparams(price=price_minor, name=name)
        )
    # Every plan must now carry an explicit price, so drop the temporary default.
    op.alter_column("membership_plans", "price_minor", server_default=None)
    op.create_check_constraint(
        op.f("ck_membership_plans_price_minor_non_negative"),
        "membership_plans",
        "price_minor >= 0",
    )
    op.create_check_constraint(
        op.f("ck_membership_plans_duration_days_positive"),
        "membership_plans",
        "duration_days > 0",
    )

    op.add_column(
        "memberships",
        sa.Column("payment_reference", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_memberships_payment_reference"), "memberships", ["payment_reference"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_memberships_payment_reference"), "memberships", type_="unique")
    op.drop_column("memberships", "payment_reference")
    op.drop_constraint(
        op.f("ck_membership_plans_duration_days_positive"), "membership_plans", type_="check"
    )
    op.drop_constraint(
        op.f("ck_membership_plans_price_minor_non_negative"), "membership_plans", type_="check"
    )
    op.drop_column("membership_plans", "duration_days")
    op.drop_column("membership_plans", "currency")
    op.drop_column("membership_plans", "price_minor")
