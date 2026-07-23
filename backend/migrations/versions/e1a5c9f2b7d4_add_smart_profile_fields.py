"""add smart profile fields

Revision ID: e1a5c9f2b7d4
Revises: d1e7c4b9a6f3
Create Date: 2026-07-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "e1a5c9f2b7d4"
down_revision: Union[str, Sequence[str], None] = "d1e7c4b9a6f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("field_profile", JSONB, nullable=True))
    op.add_column("users", sa.Column("skills", JSONB, nullable=True))
    op.add_column("users", sa.Column("exposure", JSONB, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "exposure")
    op.drop_column("users", "skills")
    op.drop_column("users", "field_profile")
