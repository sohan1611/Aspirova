"""add opportunity closed_at

Revision ID: c2d8e4f1a9b6
Revises: b3c7d9e2f4a1
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d8e4f1a9b6"
down_revision: Union[str, Sequence[str], None] = "b3c7d9e2f4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "opportunities",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_opportunities_closed_at",
        "opportunities",
        ["closed_at"],
        unique=False,
        postgresql_where=sa.text("closed_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_opportunities_closed_at", table_name="opportunities")
    op.drop_column("opportunities", "closed_at")
