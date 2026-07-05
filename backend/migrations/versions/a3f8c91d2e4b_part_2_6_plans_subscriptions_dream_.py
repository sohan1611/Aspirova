"""part 2.6 plans subscriptions dream_companies

Revision ID: a3f8c91d2e4b
Revises: bf2369a490a6
Create Date: 2026-07-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3f8c91d2e4b"
down_revision: Union[str, Sequence[str], None] = "bf2369a490a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "plans",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("price_paise", sa.Integer(), nullable=False),
        sa.Column("billing", sa.Text(), nullable=True),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("razorpay_plan_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("razorpay_sub_id", sa.Text(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("razorpay_sub_id"),
    )
    op.create_index(
        "ix_subscriptions_user_status",
        "subscriptions",
        ["user_id", "status"],
        unique=False,
    )
    op.create_table(
        "dream_companies",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "company_id", name="uq_dream_companies_user_company"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("dream_companies")
    op.drop_index("ix_subscriptions_user_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("plans")
