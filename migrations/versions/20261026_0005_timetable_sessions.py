"""Add timetable sessions; link bookings and waitlist entries to a session."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261026_0005"
down_revision: str | None = "20261019_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("resource_name", sa.String(length=150), nullable=False),
        sa.Column("resource_type", sa.String(length=17), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("allocated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("station_count", sa.Integer(), nullable=True),
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
            "resource_type IN ('CLASS', 'POOL', 'PERSONAL_TRAINING')",
            name="ck_sessions_booking_resource_type",
        ),
        sa.CheckConstraint("capacity > 0", name="ck_sessions_capacity_positive"),
        sa.CheckConstraint(
            "allocated_count >= 0 AND allocated_count <= capacity",
            name="ck_sessions_allocated_within_capacity",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_sessions_ends_after_start"),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
    )
    op.create_index("ix_sessions_resource_name", "sessions", ["resource_name"])
    op.create_index("ix_sessions_starts_at", "sessions", ["starts_at"])

    # Bookings: optional link to a session, an end time and two new statuses.
    op.add_column("bookings", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_bookings_session_id_sessions",
        "bookings",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_bookings_session_id", "bookings", ["session_id"])
    op.drop_constraint("ck_bookings_booking_status", "bookings", type_="check")
    op.alter_column("bookings", "status", type_=sa.String(length=10))
    op.create_check_constraint(
        "ck_bookings_booking_status",
        "bookings",
        "status IN ('CONFIRMED', 'CANCELLED', 'CHECKED_IN', 'NO_SHOW')",
    )

    # Waitlist entries can now belong to a session instead of a booking.
    op.add_column("waitlist_entries", sa.Column("session_id", sa.Integer(), nullable=True))
    op.alter_column("waitlist_entries", "booking_id", nullable=True)
    op.create_foreign_key(
        "fk_waitlist_entries_session_id_sessions",
        "waitlist_entries",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_waitlist_entries_session_id", "waitlist_entries", ["session_id"])
    op.create_unique_constraint(
        "uq_waitlist_entries_session_id", "waitlist_entries", ["session_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_waitlist_entries_session_id", "waitlist_entries", type_="unique")
    op.drop_index("ix_waitlist_entries_session_id", table_name="waitlist_entries")
    op.drop_constraint(
        "fk_waitlist_entries_session_id_sessions", "waitlist_entries", type_="foreignkey"
    )
    op.execute("DELETE FROM waitlist_entries WHERE booking_id IS NULL")
    op.alter_column("waitlist_entries", "booking_id", nullable=False)
    op.drop_column("waitlist_entries", "session_id")

    op.drop_constraint("ck_bookings_booking_status", "bookings", type_="check")
    op.execute("UPDATE bookings SET status = 'CONFIRMED' WHERE status IN ('CHECKED_IN', 'NO_SHOW')")
    op.alter_column("bookings", "status", type_=sa.String(length=9))
    op.create_check_constraint(
        "ck_bookings_booking_status", "bookings", "status IN ('CONFIRMED', 'CANCELLED')"
    )
    op.drop_index("ix_bookings_session_id", table_name="bookings")
    op.drop_constraint(
        "fk_bookings_session_id_sessions", "bookings", type_="foreignkey"
    )
    op.drop_column("bookings", "ends_at")
    op.drop_column("bookings", "session_id")

    op.drop_index("ix_sessions_starts_at", table_name="sessions")
    op.drop_index("ix_sessions_resource_name", table_name="sessions")
    op.drop_table("sessions")
