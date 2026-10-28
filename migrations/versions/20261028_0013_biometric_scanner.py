"""Add indexed scanner template identification and denied-attempt auditing."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0013"
down_revision: str | None = "20261028_0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "member_profiles",
        sa.Column("biometric_template_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE member_profiles "
        "SET biometric_template_id = "
        "(md5(random()::text || clock_timestamp()::text || id::text))::uuid "
        "WHERE biometric_template_id IS NULL"
    )
    op.alter_column("member_profiles", "biometric_template_id", nullable=False)
    op.create_unique_constraint(
        op.f("uq_member_profiles_biometric_template_id"),
        "member_profiles",
        ["biometric_template_id"],
    )

    op.create_table(
        "denied_access_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("biometric_template_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("scanner_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("zone", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "zone IN ('gym_floor', 'vip_sauna', 'vip_massage', 'vip_cold_plunge')",
            name="ck_denied_access_attempts_access_zone",
        ),
        sa.CheckConstraint(
            "reason IN ('low_confidence', 'unknown_template', 'access_denied', 'zone_full')",
            name="ck_denied_access_attempts_denied_access_reason",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_denied_access_attempts")),
    )
    op.create_index(
        op.f("ix_denied_access_attempts_biometric_template_id"),
        "denied_access_attempts",
        ["biometric_template_id"],
    )
    op.create_index(
        op.f("ix_denied_access_attempts_scanner_key_fingerprint"),
        "denied_access_attempts",
        ["scanner_key_fingerprint"],
    )
    op.create_index(
        op.f("ix_denied_access_attempts_occurred_at"),
        "denied_access_attempts",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_denied_access_attempts_occurred_at"), table_name="denied_access_attempts"
    )
    op.drop_index(
        op.f("ix_denied_access_attempts_scanner_key_fingerprint"),
        table_name="denied_access_attempts",
    )
    op.drop_index(
        op.f("ix_denied_access_attempts_biometric_template_id"),
        table_name="denied_access_attempts",
    )
    op.drop_table("denied_access_attempts")
    op.drop_constraint(
        op.f("uq_member_profiles_biometric_template_id"),
        "member_profiles",
        type_="unique",
    )
    op.drop_column("member_profiles", "biometric_template_id")
