"""G7 two-step sign-in: authenticator secrets, backup codes, session stage.

Revision ID: 0018_two_step
Revises: 0017_batch_import
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_two_step"
down_revision: str | None = "0017_batch_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.Text()))
    op.add_column("users", sa.Column("totp_pending_secret", sa.Text()))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger()))
    op.add_column("users", sa.Column("two_step_due_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users",
        sa.Column("two_step_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("two_step_locked_until", sa.DateTime(timezone=True)))
    op.add_column(
        "auth_sessions",
        sa.Column("stage", sa.String(length=10), server_default="full", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_auth_sessions_stage"), "auth_sessions", "stage in ('full', 'verify', 'enrol')"
    )
    op.create_table(
        "two_step_backup_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_two_step_backup_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_two_step_backup_codes")),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_backup_codes_user_hash"),
    )
    op.create_index(op.f("ix_two_step_backup_codes_user_id"), "two_step_backup_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_two_step_backup_codes_user_id"), table_name="two_step_backup_codes")
    op.drop_table("two_step_backup_codes")
    op.drop_constraint(op.f("ck_auth_sessions_stage"), "auth_sessions", type_="check")
    op.drop_column("auth_sessions", "stage")
    for column in (
        "two_step_locked_until",
        "two_step_failures",
        "two_step_due_at",
        "totp_last_step",
        "totp_enabled_at",
        "totp_pending_secret",
        "totp_secret",
    ):
        op.drop_column("users", column)
