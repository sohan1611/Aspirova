"""Add company logo hints and resolution metadata.

Revision ID: c8f2a6d4e9b1
Revises: b4e8a2c6f1d9
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c8f2a6d4e9b1"
down_revision: str | Sequence[str] | None = "b4e8a2c6f1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("logo_status", sa.Text(), nullable=True))
    op.add_column("companies", sa.Column("logo_source", sa.Text(), nullable=True))
    op.add_column(
        "companies", sa.Column("logo_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("companies", sa.Column("logo_hint_url", sa.Text(), nullable=True))
    op.add_column("companies", sa.Column("logo_evidence", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "logo_evidence")
    op.drop_column("companies", "logo_hint_url")
    op.drop_column("companies", "logo_checked_at")
    op.drop_column("companies", "logo_source")
    op.drop_column("companies", "logo_status")
