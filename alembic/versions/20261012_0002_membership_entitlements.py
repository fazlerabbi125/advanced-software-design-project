from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261012_0002"
down_revision: str | None = "20261011_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_entitlements",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("entitlement", sa.String(length=17), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entitlement IN ('GYM_FLOOR_ACCESS', 'CLASS_BOOKING', 'POOL_BOOKING', "
            "'REFRESHMENTS', 'PERSONAL_TRAINING', 'TRAINING_PLANS', 'VIP_AREA_ACCESS')",
            name=op.f("ck_plan_entitlements_membership_entitlement"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["membership_plans.id"],
            name=op.f("fk_plan_entitlements_plan_id_membership_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_entitlements")),
        sa.UniqueConstraint("plan_id", "entitlement", name=op.f("uq_plan_entitlements_plan_id")),
    )
    op.create_index(
        op.f("ix_plan_entitlements_plan_id"), "plan_entitlements", ["plan_id"], unique=False
    )
    op.add_column(
        "bookings",
        sa.Column("resource_type", sa.String(length=17), nullable=True),
    )
    op.execute("UPDATE bookings SET resource_type = 'CLASS'")
    op.alter_column("bookings", "resource_type", nullable=False)
    op.create_check_constraint(
        op.f("ck_bookings_booking_resource_type"),
        "bookings",
        "resource_type IN ('CLASS', 'POOL', 'PERSONAL_TRAINING')",
    )
    op.execute(
        "INSERT INTO membership_plans (name, is_premium, is_active) "
        "VALUES ('Basic', false, true), ('Standard', false, true), ('Premium', true, true) "
        "ON CONFLICT (name) DO NOTHING"
    )
    op.execute(
        "INSERT INTO plan_entitlements (plan_id, entitlement) "
        "SELECT id, 'GYM_FLOOR_ACCESS' FROM membership_plans "
        "ON CONFLICT (plan_id, entitlement) DO NOTHING"
    )
    op.execute(
        "INSERT INTO plan_entitlements (plan_id, entitlement) "
        "SELECT id, entitlement FROM membership_plans "
        "CROSS JOIN (VALUES ('CLASS_BOOKING'), ('POOL_BOOKING')) AS benefits(entitlement) "
        "WHERE lower(name) IN ('standard', 'premium') "
        "ON CONFLICT (plan_id, entitlement) DO NOTHING"
    )
    op.execute(
        "INSERT INTO plan_entitlements (plan_id, entitlement) "
        "SELECT id, entitlement FROM membership_plans "
        "CROSS JOIN (VALUES ('CLASS_BOOKING'), ('POOL_BOOKING'), ('REFRESHMENTS'), "
        "('PERSONAL_TRAINING'), ('TRAINING_PLANS'), ('VIP_AREA_ACCESS')) AS benefits(entitlement) "
        "WHERE lower(name) = 'premium' OR is_premium = true "
        "ON CONFLICT (plan_id, entitlement) DO NOTHING"
    )
    op.drop_column("membership_plans", "is_premium")


def downgrade() -> None:
    op.add_column(
        "membership_plans",
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE membership_plans SET is_premium = true "
        "WHERE id IN ("
        "SELECT plan_id FROM plan_entitlements WHERE entitlement = 'VIP_AREA_ACCESS'"
        ")"
    )
    op.drop_index(op.f("ix_plan_entitlements_plan_id"), table_name="plan_entitlements")
    op.drop_table("plan_entitlements")
    op.drop_constraint(op.f("ck_bookings_booking_resource_type"), "bookings", type_="check")
    op.drop_column("bookings", "resource_type")
