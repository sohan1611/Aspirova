"""add subscription cancel at period end

Revision ID: f8d3c6a1b4e7
Revises: f7b2c9e4d1a6
Create Date: 2026-07-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8d3c6a1b4e7"
down_revision: Union[str, Sequence[str], None] = "f7b2c9e4d1a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "subscriptions",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("subscriptions", "cancel_at_period_end")
