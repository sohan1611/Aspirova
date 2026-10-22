"""add google indexing notifications

Revision ID: 3e7a9c1d5b2f
Revises: 91f4a7c2d8e3
Create Date: 2026-10-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3e7a9c1d5b2f"
down_revision: Union[str, Sequence[str], None] = "91f4a7c2d8e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "google_indexing_notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("opportunity_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "notified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('opened', 'closed')",
            name="ck_google_indexing_notifications_reason",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "reason",
            name="uq_google_indexing_notifications_opportunity_reason",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("google_indexing_notifications")
