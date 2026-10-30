"""G3 company-customisable roles and the self-approval setting.

Revision ID: 0015_roles
Revises: 0014_stock
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_roles"
down_revision: str | None = "0014_stock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STANDARD = (
    "'owner', 'administrator', 'production_manager', 'production_coordinator', "
    "'procurement', 'stores', 'quality', 'dispatch', 'finance', 'approver', 'read_only'"
)


def upgrade() -> None:
    op.create_table(
        "tenant_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_standard", sa.Boolean(), nullable=False),
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
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("key = lower(key)", name=op.f("ck_tenant_roles_key_lowercase")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tenant_roles_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_roles_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_tenant_roles_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_roles")),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_roles_key"),
    )
    op.create_index(op.f("ix_tenant_roles_tenant_id"), "tenant_roles", ["tenant_id"], unique=False)
    op.add_column(
        "fulfillment_settings",
        sa.Column(
            "allow_self_approval", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    # Roles are configurable now; the key is checked against the company's roles in code.
    op.drop_constraint(op.f("ck_tenant_memberships_role"), "tenant_memberships", type_="check")
    op.create_check_constraint(
        op.f("ck_tenant_memberships_role_key"), "tenant_memberships", "role = lower(role)"
    )


def downgrade() -> None:
    # Members holding a company's own role fall back to read-only before the fixed list returns.
    op.execute(f"UPDATE tenant_memberships SET role = 'read_only' WHERE role NOT IN ({STANDARD})")
    op.drop_constraint(op.f("ck_tenant_memberships_role_key"), "tenant_memberships", type_="check")
    op.create_check_constraint(
        op.f("ck_tenant_memberships_role"), "tenant_memberships", f"role in ({STANDARD})"
    )
    op.drop_column("fulfillment_settings", "allow_self_approval")
    op.drop_index(op.f("ix_tenant_roles_tenant_id"), table_name="tenant_roles")
    op.drop_table("tenant_roles")
