"""resume match HNSW cosine index

Revision ID: e8c4f1a6b2d9
Revises: d4b9a2e7c6f1
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8c4f1a6b2d9"
down_revision: Union[str, Sequence[str], None] = "d4b9a2e7c6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opportunities_embedding_hnsw "
        "ON opportunities USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_opportunities_embedding_hnsw")
