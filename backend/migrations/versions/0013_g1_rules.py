"""G1 rules: reconciliation tolerance, manual batch priority, dispatch exception approval,
and the same-person flag on quality decisions.

Revision ID: 0013_g1_rules
Revises: 0012_dispatch
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_g1_rules"
down_revision: str | None = "0012_dispatch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("batch_allocations", sa.Column("priority_rank", sa.Integer(), nullable=True))
    op.add_column(
        "batch_allocations", sa.Column("priority_reason", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "batch_allocations",
        sa.Column("priority_set_by_label", sa.String(length=400), nullable=True),
    )
    op.add_column(
        "batch_allocations", sa.Column("priority_set_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("dispatch_notes", sa.Column("decided_by", sa.Uuid(), nullable=True))
    op.add_column(
        "dispatch_notes", sa.Column("decided_by_label", sa.String(length=400), nullable=True)
    )
    op.add_column(
        "dispatch_notes", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "dispatch_notes", sa.Column("decision_note", sa.String(length=500), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_dispatch_notes_decided_by_users"),
        "dispatch_notes",
        "users",
        ["decided_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "fulfillment_settings",
        sa.Column(
            "reconciliation_tolerance_percent",
            sa.Numeric(precision=5, scale=2),
            server_default="2",
            nullable=False,
        ),
    )
    op.add_column(
        "quality_decisions",
        sa.Column("same_person", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "supplier_updates",
        sa.Column(
            "unaccounted_qty", sa.Numeric(precision=18, scale=6), server_default="0", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_fulfillment_settings_tolerance_range"),
        "fulfillment_settings",
        "reconciliation_tolerance_percent >= 0 AND reconciliation_tolerance_percent <= 20",
    )
    op.create_check_constraint(
        op.f("ck_batch_allocations_priority"),
        "batch_allocations",
        "priority_rank IS NULL OR priority_rank between 1 and 99",
    )
    # Dispatch exceptions are requested first, then approved or rejected.
    op.drop_constraint(op.f("ck_dispatch_notes_status"), "dispatch_notes", type_="check")
    op.create_check_constraint(
        op.f("ck_dispatch_notes_status"),
        "dispatch_notes",
        "status in ('pending_approval', 'posted', 'rejected', 'cancelled')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM dispatch_notes WHERE status IN ('pending_approval', 'rejected')")
    op.drop_constraint(op.f("ck_dispatch_notes_status"), "dispatch_notes", type_="check")
    op.create_check_constraint(
        op.f("ck_dispatch_notes_status"), "dispatch_notes", "status in ('posted', 'cancelled')"
    )
    op.drop_constraint(op.f("ck_batch_allocations_priority"), "batch_allocations", type_="check")
    op.drop_constraint(
        op.f("ck_fulfillment_settings_tolerance_range"), "fulfillment_settings", type_="check"
    )
    op.drop_column("supplier_updates", "unaccounted_qty")
    op.drop_column("quality_decisions", "same_person")
    op.drop_column("fulfillment_settings", "reconciliation_tolerance_percent")
    op.drop_constraint(
        op.f("fk_dispatch_notes_decided_by_users"), "dispatch_notes", type_="foreignkey"
    )
    op.drop_column("dispatch_notes", "decision_note")
    op.drop_column("dispatch_notes", "decided_at")
    op.drop_column("dispatch_notes", "decided_by_label")
    op.drop_column("dispatch_notes", "decided_by")
    op.drop_column("batch_allocations", "priority_set_at")
    op.drop_column("batch_allocations", "priority_set_by_label")
    op.drop_column("batch_allocations", "priority_reason")
    op.drop_column("batch_allocations", "priority_rank")
