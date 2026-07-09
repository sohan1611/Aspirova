"""add company global rank

Revision ID: b7e3c9d2a1f4
Revises: c6d8e3f1a4b2
Create Date: 2026-07-09 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3c9d2a1f4"
down_revision: Union[str, Sequence[str], None] = "c6d8e3f1a4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("companies", sa.Column("global_rank", sa.Integer(), nullable=True))
    op.create_index("ix_companies_global_rank", "companies", ["global_rank"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_companies_global_rank", table_name="companies")
    op.drop_column("companies", "global_rank")
