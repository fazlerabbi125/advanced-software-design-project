from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership_plans",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_premium", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_plans")),
        sa.UniqueConstraint("name", name=op.f("uq_membership_plans_name")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            "role IN ('MEMBER', 'STAFF', 'MANAGER')", name=op.f("ck_users_user_role")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "member_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("biometric_image_key", sa.String(length=512), nullable=True),
        sa.Column("biometric_content_type", sa.String(length=100), nullable=True),
        sa.Column("biometric_uploaded_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_member_profiles_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_member_profiles")),
        sa.UniqueConstraint(
            "biometric_image_key", name=op.f("uq_member_profiles_biometric_image_key")
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_member_profiles_user_id")),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
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
            "status IN ('ACTIVE', 'EXPIRED', 'CANCELLED')",
            name=op.f("ck_memberships_membership_status"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["membership_plans.id"],
            name=op.f("fk_memberships_plan_id_membership_plans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memberships_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
    )
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)
    op.create_index(op.f("ix_memberships_ends_on"), "memberships", ["ends_on"], unique=False)
    op.create_table(
        "bookings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resource_name", sa.String(length=150), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
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
            "status IN ('CONFIRMED', 'CANCELLED')", name=op.f("ck_bookings_booking_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_bookings_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        sa.UniqueConstraint(
            "user_id", "resource_name", "starts_at", name=op.f("uq_bookings_user_id")
        ),
    )
    op.create_index(op.f("ix_bookings_resource_name"), "bookings", ["resource_name"], unique=False)
    op.create_index(op.f("ix_bookings_starts_at"), "bookings", ["starts_at"], unique=False)
    op.create_index(op.f("ix_bookings_user_id"), "bookings", ["user_id"], unique=False)
    op.create_table(
        "access_logs",
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=15), nullable=False),
        sa.Column("zone", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
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
            "event IN ('CHECK_IN', 'CHECK_OUT', 'MANUAL_CHECK_IN')",
            name=op.f("ck_access_logs_access_event"),
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["users.id"], name=op.f("fk_access_logs_member_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_logs")),
    )
    op.create_index(op.f("ix_access_logs_member_id"), "access_logs", ["member_id"], unique=False)
    op.create_index(
        op.f("ix_access_logs_occurred_at"), "access_logs", ["occurred_at"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("jti", name=op.f("uq_refresh_tokens_jti")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "waitlist_entries",
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('WAITING', 'OFFERED', 'ACCEPTED', 'EXPIRED')",
            name=op.f("ck_waitlist_entries_waitlist_status"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_waitlist_entries_booking_id_bookings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_waitlist_entries_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waitlist_entries")),
        sa.UniqueConstraint("booking_id", "user_id", name=op.f("uq_waitlist_entries_booking_id")),
    )
    op.create_index(
        op.f("ix_waitlist_entries_booking_id"), "waitlist_entries", ["booking_id"], unique=False
    )
    op.create_index(
        op.f("ix_waitlist_entries_user_id"), "waitlist_entries", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("waitlist_entries")
    op.drop_table("refresh_tokens")
    op.drop_table("access_logs")
    op.drop_table("bookings")
    op.drop_table("memberships")
    op.drop_table("member_profiles")
    op.drop_table("users")
    op.drop_table("membership_plans")
