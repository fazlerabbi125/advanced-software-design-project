"""Link pending early renewals to the active membership they supersede."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0014"
down_revision: str | None = "20261028_0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memberships",
        sa.Column("renewed_from_membership_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_memberships_renewed_from_membership_id_memberships",
        "memberships",
        "memberships",
        ["renewed_from_membership_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_memberships_renewed_from_membership_id_memberships",
        "memberships",
        type_="foreignkey",
    )
    op.drop_column("memberships", "renewed_from_membership_id")
