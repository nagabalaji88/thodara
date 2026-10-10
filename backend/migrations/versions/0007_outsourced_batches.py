"""Add outsourced batches, custody movements and order allocations.

Revision ID: 0007_outsourced_batches
Revises: 0006_order_dependencies
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_outsourced_batches"
down_revision: str | None = "0006_order_dependencies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outsourced_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("expected_return_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sent_date", sa.Date(), nullable=True),
        sa.Column("challan_reference", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status_reason", sa.String(length=500), nullable=True),
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
            "status in ('planned', 'at_supplier', 'closed', 'cancelled')",
            name=op.f("ck_outsourced_batches_status"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_outsourced_batches_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_outsourced_batches_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            name="fk_outsourced_batches_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_outsourced_batches_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_outsourced_batches_supplier",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name="fk_outsourced_batches_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_outsourced_batches_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_outsourced_batches_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outsourced_batches")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_outsourced_batches_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_outsourced_batches_number"),
    )
    op.create_index(
        op.f("ix_outsourced_batches_site_id"), "outsourced_batches", ["site_id"], unique=False
    )
    op.create_index(
        op.f("ix_outsourced_batches_supplier_id"),
        "outsourced_batches",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "ix_outsourced_batches_tenant_status",
        "outsourced_batches",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_table(
        "batch_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("document_reference", sa.String(length=80), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("recorded_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind in ('sent_to_supplier')", name=op.f("ck_batch_movements_kind")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_batch_movements_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name=op.f("fk_batch_movements_recorded_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            name="fk_batch_movements_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch_movements")),
    )
    op.create_index(
        op.f("ix_batch_movements_batch_id"), "batch_movements", ["batch_id"], unique=False
    )
    op.create_table(
        "batch_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_batch_allocations_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_batch_allocations_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            name="fk_batch_allocations_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "component_id"],
            ["order_line_components.tenant_id", "order_line_components.id"],
            name="fk_batch_allocations_component",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch_allocations")),
        sa.UniqueConstraint("batch_id", "component_id", name="uq_batch_allocations_component"),
    )
    op.create_index(
        op.f("ix_batch_allocations_batch_id"), "batch_allocations", ["batch_id"], unique=False
    )
    op.create_index(
        op.f("ix_batch_allocations_component_id"),
        "batch_allocations",
        ["component_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_batch_allocations_component_id"), table_name="batch_allocations")
    op.drop_index(op.f("ix_batch_allocations_batch_id"), table_name="batch_allocations")
    op.drop_table("batch_allocations")
    op.drop_index(op.f("ix_batch_movements_batch_id"), table_name="batch_movements")
    op.drop_table("batch_movements")
    op.drop_index("ix_outsourced_batches_tenant_status", table_name="outsourced_batches")
    op.drop_index(op.f("ix_outsourced_batches_supplier_id"), table_name="outsourced_batches")
    op.drop_index(op.f("ix_outsourced_batches_site_id"), table_name="outsourced_batches")
    op.drop_table("outsourced_batches")
