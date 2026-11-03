"""Add domains to company follows.

Revision ID: b4e8a2c6f1d9
Revises: a2c6e9f4b8d1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b4e8a2c6f1d9"
down_revision: str | Sequence[str] | None = "a2c6e9f4b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dream_companies",
        sa.Column(
            "roles", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
    )


def downgrade() -> None:
    op.drop_column("dream_companies", "roles")
