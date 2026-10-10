"""Add supplier updates for outsourced batches.

Revision ID: 0008_supplier_updates
Revises: 0007_outsourced_batches
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_supplier_updates"
down_revision: str | None = "0007_outsourced_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_updates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("completed_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rejected_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("pending_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("revised_return_date", sa.Date(), nullable=True),
        sa.Column("blocker", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("contact_method", sa.String(length=20), nullable=False),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmation_state", sa.String(length=40), nullable=False),
        sa.Column("corrects_id", sa.Uuid(), nullable=True),
        sa.Column("correction_reason", sa.String(length=500), nullable=True),
        sa.Column("submission_key", sa.Uuid(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("recorded_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confirmation_state in ('supplier_confirmation_pending')",
            name=op.f("ck_supplier_updates_confirmation_state"),
        ),
        sa.CheckConstraint(
            "contact_method in ('phone', 'whatsapp', 'email', 'visit', 'other')",
            name=op.f("ck_supplier_updates_contact_method"),
        ),
        sa.CheckConstraint(
            "source in ('manufacturer_entered')", name=op.f("ck_supplier_updates_source")
        ),
        sa.CheckConstraint(
            "(corrects_id IS NULL) = (correction_reason IS NULL)",
            name=op.f("ck_supplier_updates_correction_reason"),
        ),
        sa.CheckConstraint(
            "completed_qty >= 0 AND rejected_qty >= 0 AND pending_qty >= 0",
            name=op.f("ck_supplier_updates_quantities"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name=op.f("fk_supplier_updates_recorded_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            name="fk_supplier_updates_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "corrects_id"],
            ["supplier_updates.tenant_id", "supplier_updates.id"],
            name="fk_supplier_updates_corrects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_updates")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supplier_updates_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "submission_key", name="uq_supplier_updates_submission"),
    )
    op.create_index(
        op.f("ix_supplier_updates_batch_id"), "supplier_updates", ["batch_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_supplier_updates_batch_id"), table_name="supplier_updates")
    op.drop_table("supplier_updates")
