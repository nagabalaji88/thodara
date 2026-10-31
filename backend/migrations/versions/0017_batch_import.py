"""G6 batch reference and material owner (for importing outsourced batches).

Revision ID: 0017_batch_import
Revises: 0016_language
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_batch_import"
down_revision: str | None = "0016_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outsourced_batches", sa.Column("reference", sa.String(length=80)))
    op.add_column(
        "outsourced_batches",
        sa.Column("material_owner", sa.String(length=10), server_default="own", nullable=False),
    )
    op.add_column("outsourced_batches", sa.Column("owner_customer_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_outsourced_batches_owner_customer",
        "outsourced_batches",
        "customers",
        ["tenant_id", "owner_customer_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_outsourced_batches_material_owner"),
        "outsourced_batches",
        "(material_owner = 'own' AND owner_customer_id IS NULL) OR "
        "(material_owner = 'customer' AND owner_customer_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_outsourced_batches_material_owner"), "outsourced_batches", type_="check"
    )
    op.drop_constraint(
        "fk_outsourced_batches_owner_customer", "outsourced_batches", type_="foreignkey"
    )
    op.drop_column("outsourced_batches", "owner_customer_id")
    op.drop_column("outsourced_batches", "material_owner")
    op.drop_column("outsourced_batches", "reference")
