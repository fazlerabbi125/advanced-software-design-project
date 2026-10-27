"""Waiting lists belong to timetable sessions only; drop the old booking-based link."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0007"
down_revision: str | None = "20261026_0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Entries from the old booking-based waiting list have no session and cannot be
    # offered a place, so they are removed.
    op.execute("DELETE FROM waitlist_entries WHERE session_id IS NULL")
    op.drop_constraint("uq_waitlist_entries_booking_id", "waitlist_entries", type_="unique")
    op.drop_constraint(
        "fk_waitlist_entries_booking_id_bookings", "waitlist_entries", type_="foreignkey"
    )
    op.drop_index("ix_waitlist_entries_booking_id", table_name="waitlist_entries")
    op.drop_column("waitlist_entries", "booking_id")
    op.alter_column("waitlist_entries", "session_id", nullable=False)


def downgrade() -> None:
    op.alter_column("waitlist_entries", "session_id", nullable=True)
    op.add_column("waitlist_entries", sa.Column("booking_id", sa.Integer(), nullable=True))
    op.create_index("ix_waitlist_entries_booking_id", "waitlist_entries", ["booking_id"])
    op.create_foreign_key(
        "fk_waitlist_entries_booking_id_bookings",
        "waitlist_entries",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_waitlist_entries_booking_id", "waitlist_entries", ["booking_id", "user_id"]
    )
