"""add user invite codes

Revision ID: f2a9c7d4e1b0
Revises: e8c4f1a6b2d9
Create Date: 2026-07-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a9c7d4e1b0"
down_revision: Union[str, Sequence[str], None] = "e8c4f1a6b2d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("invite_code", sa.Text(), nullable=True))
    op.create_index("ix_users_invite_code_unique", "users", ["invite_code"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_users_invite_code_unique", table_name="users")
    op.drop_column("users", "invite_code")
