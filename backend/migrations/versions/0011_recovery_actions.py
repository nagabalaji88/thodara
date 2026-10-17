"""Add recovery actions and their history.

Revision ID: 0011_recovery_actions
Revises: 0010_fulfillment_settings
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_recovery_actions"
down_revision: str | None = "0010_fulfillment_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("owner_label", sa.String(length=400), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_before", sa.JSON(), nullable=True),
        sa.Column("risk_after", sa.JSON(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supplier_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("outcome_note", sa.String(length=1000), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_key", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_by_label", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            (
                "kind in ('chase_update', 'collect', 'expedite', 'overtime', "
                "'resequence', 'rework', 'alternate_supplier', 'promise_review', "
                "'other')"
            ),
            name=op.f("ck_recovery_actions_kind"),
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome in ('resolved', 'partly_resolved', 'not_resolved')",
            name=op.f("ck_recovery_actions_outcome"),
        ),
        sa.CheckConstraint(
            "status in ('awaiting_approval', 'open', 'done', 'rejected', 'cancelled')",
            name=op.f("ck_recovery_actions_status"),
        ),
        sa.CheckConstraint(
            "line_id IS NOT NULL OR batch_id IS NOT NULL",
            name=op.f("ck_recovery_actions_has_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_recovery_actions_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_recovery_actions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_recovery_actions_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            name="fk_recovery_actions_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            name="fk_recovery_actions_line",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_recovery_actions_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_recovery_actions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_actions")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_recovery_actions_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "submission_key", name="uq_recovery_actions_submission"),
    )
    op.create_index(
        op.f("ix_recovery_actions_batch_id"), "recovery_actions", ["batch_id"], unique=False
    )
    op.create_index(
        op.f("ix_recovery_actions_line_id"), "recovery_actions", ["line_id"], unique=False
    )
    op.create_index(
        op.f("ix_recovery_actions_owner_id"), "recovery_actions", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_recovery_actions_site_id"), "recovery_actions", ["site_id"], unique=False
    )
    op.create_index(
        "ix_recovery_actions_tenant_status",
        "recovery_actions",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_table(
        "action_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "kind in ('created', 'approved', 'rejected', 'acknowledged', "
                "'supplier_acknowledged', 'reassigned', 'completed', 'cancelled')"
            ),
            name=op.f("ck_action_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_action_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "action_id"],
            ["recovery_actions.tenant_id", "recovery_actions.id"],
            name="fk_action_events_action",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_events")),
    )
    op.create_index(
        op.f("ix_action_events_action_id"), "action_events", ["action_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_action_events_action_id"), table_name="action_events")
    op.drop_table("action_events")
    op.drop_index("ix_recovery_actions_tenant_status", table_name="recovery_actions")
    op.drop_index(op.f("ix_recovery_actions_site_id"), table_name="recovery_actions")
    op.drop_index(op.f("ix_recovery_actions_owner_id"), table_name="recovery_actions")
    op.drop_index(op.f("ix_recovery_actions_line_id"), table_name="recovery_actions")
    op.drop_index(op.f("ix_recovery_actions_batch_id"), table_name="recovery_actions")
    op.drop_table("recovery_actions")
