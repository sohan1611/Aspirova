"""add opportunity action counts

Revision ID: a2c6e9f4b8d1
Revises: 6b2d9f4a8c1e
Create Date: 2026-11-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2c6e9f4b8d1"
down_revision: Union[str, Sequence[str], None] = "6b2d9f4a8c1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "opportunity_action_counts",
        sa.Column("opportunity_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("opportunity_id", "action", "day"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("opportunity_action_counts")
