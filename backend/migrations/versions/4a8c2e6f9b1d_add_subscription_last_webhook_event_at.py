"""add subscription last webhook event at

Revision ID: 4a8c2e6f9b1d
Revises: 3e7a9c1d5b2f
Create Date: 2026-11-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a8c2e6f9b1d"
down_revision: Union[str, Sequence[str], None] = "3e7a9c1d5b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "subscriptions",
        sa.Column("last_webhook_event_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("subscriptions", "last_webhook_event_at")
