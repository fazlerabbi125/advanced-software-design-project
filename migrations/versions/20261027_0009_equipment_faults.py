"""Equipment units, fault reports and equipment slots on the timetable."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0009"
down_revision: str | None = "20261027_0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

OLD_RESOURCE_TYPES = "resource_type IN ('class', 'pool', 'personal_training')"
NEW_RESOURCE_TYPES = "resource_type IN ('class', 'pool', 'personal_training', 'equipment')"
RESOURCE_TYPE_CHECKS = (
    ("bookings", "ck_bookings_booking_resource_type"),
    ("timetable_sessions", "ck_timetable_sessions_booking_resource_type"),
)


def upgrade() -> None:
    op.create_table(
        "equipment_units",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("equipment_type", sa.String(length=50), nullable=False),
        sa.Column("zone", sa.String(length=100), nullable=False),
        sa.Column("in_service", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_units")),
        sa.UniqueConstraint("name", name=op.f("uq_equipment_units_name")),
    )
    op.create_index(
        op.f("ix_equipment_units_equipment_type"), "equipment_units", ["equipment_type"]
    )
    op.create_table(
        "equipment_faults",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("reported_by_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('reported', 'confirmed', 'dismissed', 'resolved')",
            name="ck_equipment_faults_equipment_fault_status",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["equipment_units.id"],
            name=op.f("fk_equipment_faults_unit_id_equipment_units"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by_id"],
            ["users.id"],
            name=op.f("fk_equipment_faults_reported_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_equipment_faults_reviewed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_equipment_faults_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_faults")),
    )
    for column in ("unit_id", "reported_by_id", "status"):
        op.create_index(op.f(f"ix_equipment_faults_{column}"), "equipment_faults", [column])

    op.add_column("timetable_sessions", sa.Column("equipment_unit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_timetable_sessions_equipment_unit_id_equipment_units"),
        "timetable_sessions",
        "equipment_units",
        ["equipment_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_timetable_sessions_equipment_unit_id"),
        "timetable_sessions",
        ["equipment_unit_id"],
    )
    for table, name in RESOURCE_TYPE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, NEW_RESOURCE_TYPES)


def downgrade() -> None:
    op.execute("DELETE FROM bookings WHERE resource_type = 'equipment'")
    op.execute(
        "DELETE FROM waitlist_entries WHERE session_id IN "
        "(SELECT id FROM timetable_sessions WHERE resource_type = 'equipment')"
    )
    op.execute("DELETE FROM timetable_sessions WHERE resource_type = 'equipment'")
    for table, name in RESOURCE_TYPE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, OLD_RESOURCE_TYPES)
    op.drop_index(op.f("ix_timetable_sessions_equipment_unit_id"), table_name="timetable_sessions")
    op.drop_constraint(
        op.f("fk_timetable_sessions_equipment_unit_id_equipment_units"),
        "timetable_sessions",
        type_="foreignkey",
    )
    op.drop_column("timetable_sessions", "equipment_unit_id")
    for column in ("unit_id", "reported_by_id", "status"):
        op.drop_index(op.f(f"ix_equipment_faults_{column}"), table_name="equipment_faults")
    op.drop_table("equipment_faults")
    op.drop_index(op.f("ix_equipment_units_equipment_type"), table_name="equipment_units")
    op.drop_table("equipment_units")
