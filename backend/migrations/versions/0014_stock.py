"""G2 basic stock: a ledger of stock movements and a balance per warehouse and item.

Revision ID: 0014_stock
Revises: 0013_g1_rules
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_stock"
down_revision: str | None = "0013_g1_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_balances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("on_hand", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("on_hand >= 0", name=op.f("ck_stock_balances_not_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            name="fk_stock_balances_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_stock_balances_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_stock_balances_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_stock_balances_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_balances")),
        sa.UniqueConstraint("tenant_id", "warehouse_id", "item_id", name="uq_stock_balances_place"),
    )
    op.create_index(op.f("ix_stock_balances_item_id"), "stock_balances", ["item_id"], unique=False)
    op.create_index(op.f("ix_stock_balances_site_id"), "stock_balances", ["site_id"], unique=False)
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("reference", sa.String(length=80), nullable=True),
        sa.Column("balance_after", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("dispatch_id", sa.Uuid(), nullable=True),
        sa.Column("submission_key", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by_label", sa.String(length=400), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind in ('opening', 'receipt', 'issue', 'adjustment', 'dispatch', 'reversal')",
            name=op.f("ck_stock_movements_kind"),
        ),
        sa.CheckConstraint(
            "status in ('pending_approval', 'posted', 'rejected')",
            name=op.f("ck_stock_movements_status"),
        ),
        sa.CheckConstraint("quantity <> 0", name=op.f("ck_stock_movements_quantity_nonzero")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_stock_movements_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_stock_movements_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_id"],
            ["dispatch_notes.id"],
            name=op.f("fk_stock_movements_dispatch_id_dispatch_notes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_id"],
            ["stock_movements.id"],
            name=op.f("fk_stock_movements_reverses_id_stock_movements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            name="fk_stock_movements_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_stock_movements_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_stock_movements_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_stock_movements_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_movements")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_stock_movements_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "submission_key", name="uq_stock_movements_submission"),
    )
    op.create_index(
        op.f("ix_stock_movements_dispatch_id"), "stock_movements", ["dispatch_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_item_id"), "stock_movements", ["item_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_reverses_id"), "stock_movements", ["reverses_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_site_id"), "stock_movements", ["site_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_warehouse_id"), "stock_movements", ["warehouse_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_movements_warehouse_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_site_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_reverses_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_item_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_dispatch_id"), table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index(op.f("ix_stock_balances_site_id"), table_name="stock_balances")
    op.drop_index(op.f("ix_stock_balances_item_id"), table_name="stock_balances")
    op.drop_table("stock_balances")
