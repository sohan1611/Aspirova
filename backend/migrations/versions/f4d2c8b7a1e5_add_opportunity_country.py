"""add opportunity country

Revision ID: f4d2c8b7a1e5
Revises: e3b7a1c9d5f2
Create Date: 2026-07-12 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4d2c8b7a1e5"
down_revision: Union[str, Sequence[str], None] = "e3b7a1c9d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("opportunities", sa.Column("country", sa.String(length=2), nullable=True))
    op.create_index("ix_opportunities_country", "opportunities", ["country"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_opportunities_country", table_name="opportunities")
    op.drop_column("opportunities", "country")
