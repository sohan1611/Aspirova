"""add bookmark status

Revision ID: b9e3f7c2a6d4
Revises: f4d2c8b7a1e5
Create Date: 2026-07-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9e3f7c2a6d4"
down_revision: Union[str, Sequence[str], None] = "f4d2c8b7a1e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "bookmarks",
        sa.Column("status", sa.Text(), server_default=sa.text("'saved'"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("bookmarks", "status")
