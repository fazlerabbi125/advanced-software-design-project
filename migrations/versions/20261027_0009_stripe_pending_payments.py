"""Persist pending Stripe Checkout payments and verified webhook events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0009"
down_revision: str | None = "20261027_0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_memberships_membership_status", "memberships", type_="check")
    op.create_check_constraint(
        "ck_memberships_membership_status",
        "memberships",
        "status IN ('active', 'expired', 'pending', 'cancelled')",
    )
    op.alter_column(
        "memberships",
        "payment_reference",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.add_column(
        "memberships", sa.Column("stripe_session_id", sa.String(length=255), nullable=True)
    )
    op.create_index(
        "ix_memberships_stripe_session_id",
        "memberships",
        ["stripe_session_id"],
        unique=True,
    )
    op.create_table(
        "stripe_events",
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_stripe_events_membership_id_memberships",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stripe_events"),
        sa.UniqueConstraint("stripe_event_id", name="uq_stripe_events_stripe_event_id"),
    )
    op.create_index(
        "ix_stripe_events_membership_id", "stripe_events", ["membership_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_events_membership_id", table_name="stripe_events")
    op.drop_table("stripe_events")
    op.drop_index("ix_memberships_stripe_session_id", table_name="memberships")
    op.drop_column("memberships", "stripe_session_id")
    op.alter_column(
        "memberships",
        "payment_reference",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.drop_constraint("ck_memberships_membership_status", "memberships", type_="check")
    op.create_check_constraint(
        "ck_memberships_membership_status",
        "memberships",
        "status IN ('active', 'expired', 'cancelled')",
    )
