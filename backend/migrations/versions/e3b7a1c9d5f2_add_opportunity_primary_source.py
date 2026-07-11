"""add opportunity primary source

Revision ID: e3b7a1c9d5f2
Revises: c9f4e2a6b1d8
Create Date: 2026-07-12 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b7a1c9d5f2"
down_revision: Union[str, Sequence[str], None] = "c9f4e2a6b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("opportunities", sa.Column("primary_source", sa.Text(), nullable=True))
    op.create_index(
        "ix_opportunities_primary_source",
        "opportunities",
        ["primary_source"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_opportunities_primary_source", table_name="opportunities")
    op.drop_column("opportunities", "primary_source")
