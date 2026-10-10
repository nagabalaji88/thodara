"""Add customer orders, order lines and promise history.

Revision ID: 0005_sales_orders
Revises: 0004_calendars_numbering
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_sales_orders"
down_revision: str | None = "0004_calendars_numbering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("customer_reference", sa.String(length=80), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status_reason", sa.String(length=500), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('draft', 'confirmed', 'cancelled', 'closed')",
            name=op.f("ck_sales_orders_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_sales_orders_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_sales_orders_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_sales_orders_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sales_orders_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_sales_orders_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_orders")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_orders_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_sales_orders_number"),
    )
    op.create_index(op.f("ix_sales_orders_site_id"), "sales_orders", ["site_id"], unique=False)
    op.create_index(
        "ix_sales_orders_tenant_status", "sales_orders", ["tenant_id", "status"], unique=False
    )
    op.create_index(
        "uq_sales_orders_customer_reference",
        "sales_orders",
        ["tenant_id", "customer_id", "customer_reference"],
        unique=True,
        postgresql_where=sa.text("customer_reference IS NOT NULL"),
        sqlite_where=sa.text("customer_reference IS NOT NULL"),
    )
    op.create_table(
        "sales_order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("ordered_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("cancelled_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("short_closed_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_reason", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status in ('open', 'fulfilled', 'short_closed', 'cancelled')",
            name=op.f("ck_sales_order_lines_status"),
        ),
        sa.CheckConstraint(
            "cancelled_qty + short_closed_qty <= ordered_qty",
            name=op.f("ck_sales_order_lines_closed_within_ordered"),
        ),
        sa.CheckConstraint(
            "cancelled_qty >= 0 AND short_closed_qty >= 0",
            name=op.f("ck_sales_order_lines_closed_nonneg"),
        ),
        sa.CheckConstraint("ordered_qty > 0", name=op.f("ck_sales_order_lines_ordered_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            name="fk_sales_order_lines_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            name="fk_sales_order_lines_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name="fk_sales_order_lines_unit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_order_lines")),
        sa.UniqueConstraint("order_id", "line_no", name="uq_sales_order_lines_line_no"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_order_lines_tenant_id_id"),
    )
    op.create_index(
        op.f("ix_sales_order_lines_order_id"), "sales_order_lines", ["order_id"], unique=False
    )
    op.create_table(
        "promise_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("previous_date", sa.Date(), nullable=True),
        sa.Column("new_date", sa.Date(), nullable=False),
        sa.Column("reason_code", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("changed_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason_code in ('initial', 'customer_request', 'supplier_delay', "
            "'material_shortage', 'capacity', 'quality', 'transport', 'other')",
            name=op.f("ck_promise_changes_reason_code"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_promise_changes_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            name="fk_promise_changes_line",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promise_changes")),
    )
    op.create_index(
        op.f("ix_promise_changes_line_id"), "promise_changes", ["line_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_promise_changes_line_id"), table_name="promise_changes")
    op.drop_table("promise_changes")
    op.drop_index(op.f("ix_sales_order_lines_order_id"), table_name="sales_order_lines")
    op.drop_table("sales_order_lines")
    op.drop_index(
        "uq_sales_orders_customer_reference",
        table_name="sales_orders",
        postgresql_where=sa.text("customer_reference IS NOT NULL"),
        sqlite_where=sa.text("customer_reference IS NOT NULL"),
    )
    op.drop_index("ix_sales_orders_tenant_status", table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_site_id"), table_name="sales_orders")
    op.drop_table("sales_orders")
