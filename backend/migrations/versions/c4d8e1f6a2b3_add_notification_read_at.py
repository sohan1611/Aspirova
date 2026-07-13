"""add notification read state

Revision ID: c4d8e1f6a2b3
Revises: b9e3f7c2a6d4
Create Date: 2026-07-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8e1f6a2b3"
down_revision: Union[str, Sequence[str], None] = "b9e3f7c2a6d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notifications", "read_at")
