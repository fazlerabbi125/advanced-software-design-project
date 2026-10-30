"""Convert user references to UUIDs and align the timetable schema with the models."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0006"
down_revision: str | None = "20261026_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _integer_to_uuid(column_name: str) -> str:
    """Map existing integer user IDs to stable UUIDs before changing their type."""
    return f"lpad({column_name}::text, 32, '0')::uuid"


def upgrade() -> None:
    # Remove references before changing the users primary key and every dependent type.
    for table_name, constraint_name in (
        ("member_profiles", "fk_member_profiles_user_id_users"),
        ("memberships", "fk_memberships_user_id_users"),
        ("bookings", "fk_bookings_user_id_users"),
        ("access_logs", "fk_access_logs_member_id_users"),
        ("refresh_tokens", "fk_refresh_tokens_user_id_users"),
        ("waitlist_entries", "fk_waitlist_entries_booking_id_bookings"),
        ("waitlist_entries", "fk_waitlist_entries_user_id_users"),
        ("bookings", "fk_bookings_session_id_sessions"),
        ("waitlist_entries", "fk_waitlist_entries_session_id_sessions"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")

    # The original timetable revision used a generic table/column name. Rename them now.
    op.rename_table("sessions", "timetable_sessions")
    op.execute(
        "ALTER TABLE timetable_sessions RENAME CONSTRAINT pk_sessions TO pk_timetable_sessions"
    )
    op.execute(
        "ALTER TABLE timetable_sessions RENAME CONSTRAINT "
        "ck_sessions_booking_resource_type TO ck_timetable_sessions_booking_resource_type"
    )
    op.execute(
        "ALTER TABLE timetable_sessions RENAME CONSTRAINT "
        "ck_sessions_capacity_positive TO ck_timetable_sessions_capacity_positive"
    )
    op.execute(
        "ALTER TABLE timetable_sessions RENAME CONSTRAINT "
        "ck_sessions_allocated_within_capacity "
        "TO ck_timetable_sessions_allocated_within_capacity"
    )
    op.execute(
        "ALTER TABLE timetable_sessions RENAME CONSTRAINT "
        "ck_sessions_ends_after_start TO ck_timetable_sessions_ends_after_start"
    )
    op.execute(
        "ALTER INDEX ix_sessions_resource_name RENAME TO ix_timetable_sessions_resource_name"
    )
    op.execute("ALTER INDEX ix_sessions_starts_at RENAME TO ix_timetable_sessions_starts_at")
    op.alter_column("bookings", "session_id", new_column_name="timetable_session_id")
    op.execute("ALTER INDEX ix_bookings_session_id RENAME TO ix_bookings_timetable_session_id")

    # Create profile fields before making name mandatory, retaining a safe value for old rows.
    op.add_column("member_profiles", sa.Column("name", sa.String(length=200), nullable=True))
    op.add_column("member_profiles", sa.Column("phone", sa.String(length=30), nullable=True))
    op.execute(
        "UPDATE member_profiles SET name = users.email "
        "FROM users WHERE member_profiles.user_id = users.id"
    )
    op.alter_column("member_profiles", "name", nullable=False)

    op.drop_constraint("uq_refresh_tokens_token_hash", "refresh_tokens", type_="unique")
    op.drop_column("refresh_tokens", "token_hash")
    op.alter_column(
        "access_logs",
        "zone",
        existing_type=sa.String(length=100),
        type_=sa.String(150),
    )

    # The previous SERIAL key has a sequence-backed integer default. New user IDs come from
    # the model's uuid4 default, so remove the incompatible database default first.
    op.alter_column("users", "id", server_default=None)
    op.alter_column(
        "users",
        "id",
        existing_type=sa.Integer(),
        type_=sa.Uuid(as_uuid=True),
        postgresql_using=_integer_to_uuid("id"),
    )
    for table_name, column_name in (
        ("member_profiles", "user_id"),
        ("memberships", "user_id"),
        ("bookings", "user_id"),
        ("access_logs", "member_id"),
        ("refresh_tokens", "user_id"),
        ("waitlist_entries", "user_id"),
    ):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Integer(),
            type_=sa.Uuid(as_uuid=True),
            postgresql_using=_integer_to_uuid(column_name),
        )

    op.create_foreign_key(
        "fk_member_profiles_user_id_users",
        "member_profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_memberships_user_id_users",
        "memberships",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_bookings_user_id_users",
        "bookings",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_access_logs_member_id_users",
        "access_logs",
        "users",
        ["member_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_refresh_tokens_user_id_users",
        "refresh_tokens",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_waitlist_entries_booking_id_bookings",
        "waitlist_entries",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_waitlist_entries_user_id_users",
        "waitlist_entries",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_bookings_timetable_session_id_timetable_sessions",
        "bookings",
        "timetable_sessions",
        ["timetable_session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_waitlist_entries_session_id_timetable_sessions",
        "waitlist_entries",
        "timetable_sessions",
        ["session_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # SQLAlchemy now persists StrEnum.value (lowercase) instead of member names (uppercase).
    for table_name, constraint_name in (
        ("users", "ck_users_user_role"),
        ("memberships", "ck_memberships_membership_status"),
        ("bookings", "ck_bookings_booking_resource_type"),
        ("bookings", "ck_bookings_booking_status"),
        ("access_logs", "ck_access_logs_access_event"),
        ("waitlist_entries", "ck_waitlist_entries_waitlist_status"),
        ("plan_entitlements", "ck_plan_entitlements_membership_entitlement"),
        ("timetable_sessions", "ck_timetable_sessions_booking_resource_type"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="check")

    for table_name, column_name in (
        ("users", "role"),
        ("memberships", "status"),
        ("bookings", "resource_type"),
        ("bookings", "status"),
        ("access_logs", "event"),
        ("waitlist_entries", "status"),
        ("plan_entitlements", "entitlement"),
        ("timetable_sessions", "resource_type"),
    ):
        op.execute(f"UPDATE {table_name} SET {column_name} = lower({column_name})")

    op.create_check_constraint(
        "ck_users_user_role", "users", "role IN ('member', 'staff', 'manager')"
    )
    op.create_check_constraint(
        "ck_memberships_membership_status",
        "memberships",
        "status IN ('active', 'expired', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_bookings_booking_resource_type",
        "bookings",
        "resource_type IN ('class', 'pool', 'personal_training')",
    )
    op.create_check_constraint(
        "ck_bookings_booking_status",
        "bookings",
        "status IN ('confirmed', 'cancelled', 'checked_in', 'no_show')",
    )
    op.create_check_constraint(
        "ck_access_logs_access_event",
        "access_logs",
        "event IN ('check_in', 'check_out', 'manual_check_in')",
    )
    op.create_check_constraint(
        "ck_waitlist_entries_waitlist_status",
        "waitlist_entries",
        "status IN ('waiting', 'offered', 'accepted', 'expired')",
    )
    op.create_check_constraint(
        "ck_plan_entitlements_membership_entitlement",
        "plan_entitlements",
        "entitlement IN ('gym_floor_access', 'class_booking', 'pool_booking', "
        "'refreshments', 'personal_training', 'training_plans', 'vip_area_access')",
    )
    op.create_check_constraint(
        "ck_timetable_sessions_booking_resource_type",
        "timetable_sessions",
        "resource_type IN ('class', 'pool', 'personal_training')",
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrading UUID user IDs to integers is not safe.")
