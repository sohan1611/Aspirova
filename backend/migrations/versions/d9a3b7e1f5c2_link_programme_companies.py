"""Link programme organisers to canonical companies.

Revision ID: d9a3b7e1f5c2
Revises: c8f2a6d4e9b1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d9a3b7e1f5c2"
down_revision: str | Sequence[str] | None = "c8f2a6d4e9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "programmes",
        sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("programmes", "company_id")
