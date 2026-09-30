"""Add audit provenance and session metadata.

Revision ID: 0003_audit_sessions
Revises: 0002_masterdata
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_audit_sessions"
down_revision: str | None = "0002_masterdata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("actor_type", sa.String(length=20), nullable=False, server_default="user"),
    )
    op.add_column("audit_events", sa.Column("actor_label", sa.String(length=400), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("source_channel", sa.String(length=20), nullable=False, server_default="unknown"),
    )
    # Existing events: failed logins and events without an actor were never authenticated;
    # the channel of past events was not recorded.
    op.execute(
        "UPDATE audit_events SET actor_type = 'anonymous' "
        "WHERE actor_user_id IS NULL OR action = 'auth.login_failed'"
    )
    op.execute(
        "UPDATE audit_events AS e SET actor_label = u.display_name || ' <' || u.email || '>' "
        "FROM users AS u WHERE e.actor_user_id = u.id"
    )
    op.alter_column("audit_events", "actor_type", server_default=None)
    op.alter_column("audit_events", "source_channel", server_default=None)
    op.create_check_constraint(
        op.f("ck_audit_events_actor_type"),
        "audit_events",
        "actor_type in ('user', 'anonymous', 'system')",
    )
    op.create_check_constraint(
        op.f("ck_audit_events_source_channel"),
        "audit_events",
        "source_channel in ('web', 'api', 'cli', 'unknown')",
    )
    op.add_column("auth_sessions", sa.Column("user_agent", sa.String(length=255), nullable=True))
    op.add_column(
        "auth_sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("auth_sessions", "last_seen_at")
    op.drop_column("auth_sessions", "user_agent")
    op.drop_constraint(op.f("ck_audit_events_source_channel"), "audit_events", type_="check")
    op.drop_constraint(op.f("ck_audit_events_actor_type"), "audit_events", type_="check")
    op.drop_column("audit_events", "source_channel")
    op.drop_column("audit_events", "actor_label")
    op.drop_column("audit_events", "actor_type")
