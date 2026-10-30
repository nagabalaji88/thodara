"""G4 per-user screen language (English or Tamil).

Revision ID: 0016_language
Revises: 0015_roles
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_language"
down_revision: str | None = "0015_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("language", sa.String(length=5), server_default="en", nullable=False)
    )
    op.create_check_constraint(op.f("ck_users_language"), "users", "language in ('en', 'ta')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_language"), "users", type_="check")
    op.drop_column("users", "language")
