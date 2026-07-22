"""add subscription upgrade kind

Revision ID: d1e7c4b9a6f3
Revises: a9d4e6f2b8c1
Create Date: 2026-07-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e7c4b9a6f3"
down_revision: Union[str, Sequence[str], None] = "a9d4e6f2b8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # PostgreSQL applies this server default to existing rows as they are added,
    # so historic same-period upgrades are backfilled consistently.
    op.add_column(
        "subscription_upgrades",
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'same_period_upgrade'"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("subscription_upgrades", "kind")
