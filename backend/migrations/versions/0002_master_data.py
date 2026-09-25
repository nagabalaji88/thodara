"""Add master data and membership site scope.

Revision ID: 0002_masterdata
Revises: 0001_identity
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_masterdata"
down_revision: str | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing memberships: owners/administrators keep every site; everyone else keeps
    # only their home site (deny by default). See ADR-0003.
    op.add_column(
        "tenant_memberships",
        sa.Column("site_scope", sa.String(length=10), nullable=False, server_default="selected"),
    )
    op.execute(
        "UPDATE tenant_memberships SET site_scope = 'all' WHERE role IN ('owner', 'administrator')"
    )
    op.alter_column("tenant_memberships", "site_scope", server_default=None)
    op.create_check_constraint(
        op.f("ck_tenant_memberships_site_scope"),
        "tenant_memberships",
        "site_scope in ('all', 'selected')",
    )
    op.create_unique_constraint(
        "uq_tenant_memberships_tenant_id_id", "tenant_memberships", ["tenant_id", "id"]
    )
    op.create_table(
        "customers",
        sa.Column("contact_email", sa.String(length=254), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
        sa.CheckConstraint("status in ('active', 'inactive')", name=op.f("ck_customers_status")),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_customers_code_uppercase")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_customers_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_customers_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_customers_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_customers_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
    )
    op.create_index(op.f("ix_customers_tenant_id"), "customers", ["tenant_id"], unique=False)
    op.create_table(
        "suppliers",
        sa.Column("contact_email", sa.String(length=254), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("provides_job_work", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
        sa.CheckConstraint("status in ('active', 'inactive')", name=op.f("ck_suppliers_status")),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_suppliers_code_uppercase")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_suppliers_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_suppliers_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_suppliers_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_suppliers_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_suppliers_tenant_id_id"),
    )
    op.create_index(op.f("ix_suppliers_tenant_id"), "suppliers", ["tenant_id"], unique=False)
    op.create_table(
        "units_of_measure",
        sa.Column("dimension", sa.String(length=20), nullable=False),
        sa.Column("decimal_places", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            "dimension in ('count', 'mass', 'length', 'area', 'volume', 'time')",
            name=op.f("ck_units_of_measure_dimension"),
        ),
        sa.CheckConstraint(
            "status in ('active', 'inactive')", name=op.f("ck_units_of_measure_status")
        ),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_units_of_measure_code_uppercase")),
        sa.CheckConstraint(
            "decimal_places between 0 and 6", name=op.f("ck_units_of_measure_decimal_places_range")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_units_of_measure_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_units_of_measure_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_units_of_measure_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_units_of_measure")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_units_of_measure_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_units_of_measure_tenant_id_id"),
    )
    op.create_index(
        op.f("ix_units_of_measure_tenant_id"), "units_of_measure", ["tenant_id"], unique=False
    )
    op.create_table(
        "items",
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("base_unit_id", sa.Uuid(), nullable=False),
        sa.Column("tracking", sa.String(length=10), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            "item_type in ('raw_material', 'component', 'intermediate', 'finished_good', "
            "'packaging', 'consumable', 'service')",
            name=op.f("ck_items_item_type"),
        ),
        sa.CheckConstraint("status in ('active', 'inactive')", name=op.f("ck_items_status")),
        sa.CheckConstraint("tracking in ('none', 'lot', 'serial')", name=op.f("ck_items_tracking")),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_items_code_uppercase")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_items_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "base_unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name=op.f("fk_items_tenant_id_units_of_measure"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_items_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_items_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_items_tenant_id_id"),
    )
    op.create_index(op.f("ix_items_tenant_id"), "items", ["tenant_id"], unique=False)
    op.create_table(
        "unit_conversions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("from_unit_id", sa.Uuid(), nullable=False),
        sa.Column("to_unit_id", sa.Uuid(), nullable=False),
        sa.Column("factor", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("factor > 0", name=op.f("ck_unit_conversions_factor_positive")),
        sa.CheckConstraint(
            "from_unit_id <> to_unit_id", name=op.f("ck_unit_conversions_distinct_units")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_unit_conversions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "from_unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name="fk_unit_conversions_from_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "to_unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name="fk_unit_conversions_to_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_unit_conversions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unit_conversions")),
        sa.UniqueConstraint(
            "tenant_id", "from_unit_id", "to_unit_id", name="uq_unit_conversions_pair"
        ),
    )
    op.create_index(
        op.f("ix_unit_conversions_tenant_id"), "unit_conversions", ["tenant_id"], unique=False
    )
    op.create_table(
        "warehouses",
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
        sa.CheckConstraint("status in ('active', 'inactive')", name=op.f("ck_warehouses_status")),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_warehouses_code_uppercase")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_warehouses_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name=op.f("fk_warehouses_tenant_id_sites"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_warehouses_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_warehouses_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouses")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_warehouses_tenant_id_id"),
    )
    op.create_index(op.f("ix_warehouses_site_id"), "warehouses", ["site_id"], unique=False)
    op.create_index(op.f("ix_warehouses_tenant_id"), "warehouses", ["tenant_id"], unique=False)
    op.create_table(
        "membership_sites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.id"],
            name=op.f("fk_membership_sites_tenant_id_tenant_memberships"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name=op.f("fk_membership_sites_tenant_id_sites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_sites")),
        sa.UniqueConstraint("membership_id", "site_id", name="uq_membership_sites_pair"),
    )
    op.create_index(
        op.f("ix_membership_sites_tenant_id"), "membership_sites", ["tenant_id"], unique=False
    )
    op.execute(
        sa.text(
            "INSERT INTO membership_sites (id, tenant_id, membership_id, site_id) "
            "SELECT gen_random_uuid(), tenant_id, id, home_site_id FROM tenant_memberships "
            "WHERE site_scope = 'selected' AND home_site_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_membership_sites_tenant_id"), table_name="membership_sites")
    op.drop_table("membership_sites")
    op.drop_constraint("uq_tenant_memberships_tenant_id_id", "tenant_memberships", type_="unique")
    op.drop_constraint(
        op.f("ck_tenant_memberships_site_scope"), "tenant_memberships", type_="check"
    )
    op.drop_column("tenant_memberships", "site_scope")
    op.drop_index(op.f("ix_warehouses_tenant_id"), table_name="warehouses")
    op.drop_index(op.f("ix_warehouses_site_id"), table_name="warehouses")
    op.drop_table("warehouses")
    op.drop_index(op.f("ix_unit_conversions_tenant_id"), table_name="unit_conversions")
    op.drop_table("unit_conversions")
    op.drop_index(op.f("ix_items_tenant_id"), table_name="items")
    op.drop_table("items")
    op.drop_index(op.f("ix_units_of_measure_tenant_id"), table_name="units_of_measure")
    op.drop_table("units_of_measure")
    op.drop_index(op.f("ix_suppliers_tenant_id"), table_name="suppliers")
    op.drop_table("suppliers")
    op.drop_index(op.f("ix_customers_tenant_id"), table_name="customers")
    op.drop_table("customers")
