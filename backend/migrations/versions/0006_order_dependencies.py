"""Add fulfillment dependencies per customer-order line.

Revision ID: 0006_order_dependencies
Revises: 0005_sales_orders
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_order_dependencies"
down_revision: str | None = "0005_sales_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_line_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("qty_per_unit", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("outsourced_operation", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "qty_per_unit > 0", name=op.f("ck_order_line_components_qty_per_unit_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            name="fk_order_line_components_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            name="fk_order_line_components_line",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name="fk_order_line_components_unit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_line_components")),
        sa.UniqueConstraint("line_id", "item_id", name="uq_order_line_components_item"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_order_line_components_tenant_id_id"),
    )
    op.create_index(
        op.f("ix_order_line_components_line_id"), "order_line_components", ["line_id"], unique=False
    )
    op.create_table(
        "order_line_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind in ('in_house', 'transport')", name=op.f("ck_order_line_operations_kind")
        ),
        sa.CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 86400",
            name=op.f("ck_order_line_operations_duration_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            name="fk_order_line_operations_line",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_line_operations")),
        sa.UniqueConstraint("line_id", "sequence", name="uq_order_line_operations_sequence"),
    )
    op.create_index(
        op.f("ix_order_line_operations_line_id"), "order_line_operations", ["line_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_order_line_operations_line_id"), table_name="order_line_operations")
    op.drop_table("order_line_operations")
    op.drop_index(op.f("ix_order_line_components_line_id"), table_name="order_line_components")
    op.drop_table("order_line_components")
