"""Add dispatch notes, shipped quantities and consumed batch material.

Revision ID: 0012_dispatch
Revises: 0011_recovery_actions
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_dispatch"
down_revision: str | None = "0011_recovery_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dispatch_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("dispatch_date", sa.Date(), nullable=False),
        sa.Column("carrier", sa.String(length=120), nullable=True),
        sa.Column("vehicle_reference", sa.String(length=80), nullable=True),
        sa.Column("document_reference", sa.String(length=80), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("submission_key", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_by_label", sa.String(length=400), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status in ('posted', 'cancelled')", name=op.f("ck_dispatch_notes_status")
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["users.id"],
            name=op.f("fk_dispatch_notes_cancelled_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_dispatch_notes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            name="fk_dispatch_notes_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_dispatch_notes_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_dispatch_notes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispatch_notes")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_dispatch_notes_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_dispatch_notes_number"),
        sa.UniqueConstraint("tenant_id", "submission_key", name="uq_dispatch_notes_submission"),
    )
    op.create_index(
        op.f("ix_dispatch_notes_order_id"), "dispatch_notes", ["order_id"], unique=False
    )
    op.create_index(op.f("ix_dispatch_notes_site_id"), "dispatch_notes", ["site_id"], unique=False)
    op.create_table(
        "dispatch_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("on_time", sa.Boolean(), nullable=True),
        sa.Column("exception_reason", sa.String(length=500), nullable=True),
        sa.Column("consumption", sa.JSON(), nullable=True),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_dispatch_lines_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "dispatch_id"],
            ["dispatch_notes.tenant_id", "dispatch_notes.id"],
            name="fk_dispatch_lines_dispatch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            name="fk_dispatch_lines_line",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispatch_lines")),
        sa.UniqueConstraint("dispatch_id", "line_id", name="uq_dispatch_lines_line"),
    )
    op.create_index(
        op.f("ix_dispatch_lines_dispatch_id"), "dispatch_lines", ["dispatch_id"], unique=False
    )
    op.create_index(op.f("ix_dispatch_lines_line_id"), "dispatch_lines", ["line_id"], unique=False)
    op.add_column(
        "batch_allocations",
        sa.Column(
            "consumed_qty", sa.Numeric(precision=18, scale=6), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "sales_order_lines",
        sa.Column(
            "shipped_qty", sa.Numeric(precision=18, scale=6), server_default="0", nullable=False
        ),
    )
    # Shipped quantity now counts towards what a line has settled.
    op.drop_constraint(
        op.f("ck_sales_order_lines_closed_within_ordered"), "sales_order_lines", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_sales_order_lines_shipped_nonneg"), "sales_order_lines", "shipped_qty >= 0"
    )
    op.create_check_constraint(
        op.f("ck_sales_order_lines_settled_within_ordered"),
        "sales_order_lines",
        "shipped_qty + cancelled_qty + short_closed_qty <= ordered_qty",
    )
    op.create_check_constraint(
        op.f("ck_batch_allocations_consumed_range"),
        "batch_allocations",
        "consumed_qty >= 0 AND consumed_qty <= quantity",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_batch_allocations_consumed_range"), "batch_allocations", type_="check"
    )
    op.drop_constraint(
        op.f("ck_sales_order_lines_settled_within_ordered"), "sales_order_lines", type_="check"
    )
    op.drop_constraint(
        op.f("ck_sales_order_lines_shipped_nonneg"), "sales_order_lines", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_sales_order_lines_closed_within_ordered"),
        "sales_order_lines",
        "cancelled_qty + short_closed_qty <= ordered_qty",
    )
    op.drop_column("sales_order_lines", "shipped_qty")
    op.drop_column("batch_allocations", "consumed_qty")
    op.drop_index(op.f("ix_dispatch_lines_line_id"), table_name="dispatch_lines")
    op.drop_index(op.f("ix_dispatch_lines_dispatch_id"), table_name="dispatch_lines")
    op.drop_table("dispatch_lines")
    op.drop_index(op.f("ix_dispatch_notes_site_id"), table_name="dispatch_notes")
    op.drop_index(op.f("ix_dispatch_notes_order_id"), table_name="dispatch_notes")
    op.drop_table("dispatch_notes")
