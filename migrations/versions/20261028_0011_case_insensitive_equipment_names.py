"""Enforce case-insensitive equipment unit and membership plan names."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0011"
down_revision: str | None = "20261028_0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_equipment_units_name", "equipment_units", type_="unique")
    op.create_index(
        "uq_equipment_units_name_ci",
        "equipment_units",
        [sa.text("lower(name)")],
        unique=True,
    )
    op.drop_constraint("uq_membership_plans_name", "membership_plans", type_="unique")
    op.create_index(
        "uq_membership_plans_name_ci",
        "membership_plans",
        [sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_membership_plans_name_ci", table_name="membership_plans")
    op.create_unique_constraint("uq_membership_plans_name", "membership_plans", ["name"])
    op.drop_index("uq_equipment_units_name_ci", table_name="equipment_units")
    op.create_unique_constraint("uq_equipment_units_name", "equipment_units", ["name"])
