"""Add company settings for delivery risk.

Revision ID: 0010_fulfillment_settings
Revises: 0009_receipts_quality
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_fulfillment_settings"
down_revision: str | None = "0009_receipts_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fulfillment_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_update_stale_hours", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "supplier_update_stale_hours between 1 and 720",
            name=op.f("ck_fulfillment_settings_stale_hours_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_fulfillment_settings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fulfillment_settings")),
        sa.UniqueConstraint("tenant_id", name="uq_fulfillment_settings_tenant"),
    )


def downgrade() -> None:
    op.drop_table("fulfillment_settings")
