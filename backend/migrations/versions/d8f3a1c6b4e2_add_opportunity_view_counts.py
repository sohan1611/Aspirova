"""add opportunity view counts

Revision ID: d8f3a1c6b4e2
Revises: c4d8e1f6a2b3
Create Date: 2026-07-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f3a1c6b4e2"
down_revision: Union[str, Sequence[str], None] = "c4d8e1f6a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "opportunity_view_counts",
        sa.Column("opportunity_id", sa.BigInteger(), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("opportunity_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("opportunity_view_counts")
