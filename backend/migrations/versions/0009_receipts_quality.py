"""Add receipts from suppliers and quality decisions.

Revision ID: 0009_receipts_quality
Revises: 0008_supplier_updates
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_receipts_quality"
down_revision: str | None = "0008_supplier_updates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Material can now move back from the supplier as well as out to it.
    op.drop_constraint(op.f("ck_batch_movements_kind"), "batch_movements", type_="check")
    op.create_check_constraint(
        op.f("ck_batch_movements_kind"),
        "batch_movements",
        "kind in ('sent_to_supplier', 'received_from_supplier')",
    )
    op.create_table(
        "batch_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("received_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("document_reference", sa.String(length=80), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("accepted_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rejected_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("held_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rework_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("submission_key", sa.Uuid(), nullable=False),
        sa.Column("received_by", sa.Uuid(), nullable=True),
        sa.Column("received_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status in ('awaiting_inspection', 'inspected')", name=op.f("ck_batch_receipts_status")
        ),
        sa.CheckConstraint(
            "accepted_qty + rejected_qty + held_qty + rework_qty <= received_qty",
            name=op.f("ck_batch_receipts_outcomes_within_received"),
        ),
        sa.CheckConstraint(
            "accepted_qty >= 0 AND rejected_qty >= 0 AND held_qty >= 0 AND rework_qty >= 0",
            name=op.f("ck_batch_receipts_outcomes_nonneg"),
        ),
        sa.CheckConstraint("received_qty > 0", name=op.f("ck_batch_receipts_received_positive")),
        sa.ForeignKeyConstraint(
            ["received_by"],
            ["users.id"],
            name=op.f("fk_batch_receipts_received_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            name="fk_batch_receipts_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch_receipts")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_batch_receipts_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "submission_key", name="uq_batch_receipts_submission"),
    )
    op.create_index(
        op.f("ix_batch_receipts_batch_id"), "batch_receipts", ["batch_id"], unique=False
    )
    op.create_table(
        "quality_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("accepted_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rejected_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("held_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rework_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind in ('inspection', 'hold_release')", name=op.f("ck_quality_decisions_kind")
        ),
        sa.CheckConstraint(
            "accepted_qty >= 0 AND rejected_qty >= 0 AND held_qty >= 0 AND rework_qty >= 0",
            name=op.f("ck_quality_decisions_outcomes_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_quality_decisions_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["batch_receipts.tenant_id", "batch_receipts.id"],
            name="fk_quality_decisions_receipt",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_decisions")),
    )
    op.create_index(
        op.f("ix_quality_decisions_receipt_id"), "quality_decisions", ["receipt_id"], unique=False
    )


def downgrade() -> None:
    op.execute("DELETE FROM batch_movements WHERE kind = 'received_from_supplier'")
    op.drop_constraint(op.f("ck_batch_movements_kind"), "batch_movements", type_="check")
    op.create_check_constraint(
        op.f("ck_batch_movements_kind"), "batch_movements", "kind in ('sent_to_supplier')"
    )
    op.drop_index(op.f("ix_quality_decisions_receipt_id"), table_name="quality_decisions")
    op.drop_table("quality_decisions")
    op.drop_index(op.f("ix_batch_receipts_batch_id"), table_name="batch_receipts")
    op.drop_table("batch_receipts")
