"""Record which staff member performed a manual check-in, and why."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0007"
down_revision: str | None = "20261027_0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "access_logs", sa.Column("performed_by_staff_id", sa.Uuid(as_uuid=True), nullable=True)
    )
    op.add_column("access_logs", sa.Column("staff_reason", sa.String(length=255), nullable=True))
    op.create_foreign_key(
        op.f("fk_access_logs_performed_by_staff_id_users"),
        "access_logs",
        "users",
        ["performed_by_staff_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_access_logs_performed_by_staff_id"),
        "access_logs",
        ["performed_by_staff_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_logs_performed_by_staff_id"), table_name="access_logs")
    op.drop_constraint(
        op.f("fk_access_logs_performed_by_staff_id_users"), "access_logs", type_="foreignkey"
    )
    op.drop_column("access_logs", "staff_reason")
    op.drop_column("access_logs", "performed_by_staff_id")
