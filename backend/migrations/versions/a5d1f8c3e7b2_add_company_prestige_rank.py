"""add company prestige rank

Revision ID: a5d1f8c3e7b2
Revises: b7e3c9d2a1f4
Create Date: 2026-07-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5d1f8c3e7b2"
down_revision: Union[str, Sequence[str], None] = "b7e3c9d2a1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("companies", sa.Column("prestige_rank", sa.Integer(), nullable=True))
    op.create_index("ix_companies_prestige_rank", "companies", ["prestige_rank"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_companies_prestige_rank", table_name="companies")
    op.drop_column("companies", "prestige_rank")
