"""Add site working calendars, holidays and document numbering.

Revision ID: 0004_calendars_numbering
Revises: 0003_audit_sessions
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_calendars_numbering"
down_revision: str | None = "0003_audit_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_sequences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column("prefix", sa.String(length=12), nullable=False),
        sa.Column("next_number", sa.BigInteger(), nullable=False),
        sa.Column("padding", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "document_type in ('sales_order', 'outsourced_batch', 'dispatch')",
            name=op.f("ck_document_sequences_document_type"),
        ),
        sa.CheckConstraint(
            "next_number >= 1", name=op.f("ck_document_sequences_next_number_positive")
        ),
        sa.CheckConstraint(
            "padding between 1 and 10", name=op.f("ck_document_sequences_padding_range")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_document_sequences_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_sequences")),
        sa.UniqueConstraint("tenant_id", "document_type", name="uq_document_sequences_type"),
    )
    op.create_table(
        "site_calendars",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("working_days", sa.String(length=7), nullable=False),
        sa.Column("shift_start", sa.Time(), nullable=False),
        sa.Column("shift_end", sa.Time(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("shift_end > shift_start", name=op.f("ck_site_calendars_shift_order")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name=op.f("fk_site_calendars_tenant_id_sites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_site_calendars_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_calendars")),
        sa.UniqueConstraint("site_id", name="uq_site_calendars_site"),
    )
    op.create_index(
        op.f("ix_site_calendars_tenant_id"), "site_calendars", ["tenant_id"], unique=False
    )
    op.create_table(
        "site_holidays",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name=op.f("fk_site_holidays_tenant_id_sites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_holidays")),
        sa.UniqueConstraint("site_id", "holiday_date", name="uq_site_holidays_site_date"),
    )
    op.create_index(
        op.f("ix_site_holidays_tenant_id"), "site_holidays", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_site_holidays_tenant_id"), table_name="site_holidays")
    op.drop_table("site_holidays")
    op.drop_index(op.f("ix_site_calendars_tenant_id"), table_name="site_calendars")
    op.drop_table("site_calendars")
    op.drop_table("document_sequences")
