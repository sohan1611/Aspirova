"""add subscription upgrades

Revision ID: a9d4e6f2b8c1
Revises: f8d3c6a1b4e7
Create Date: 2026-07-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d4e6f2b8c1"
down_revision: Union[str, Sequence[str], None] = "f8d3c6a1b4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subscription_upgrades",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), nullable=False),
        sa.Column("from_plan_id", sa.SmallInteger(), nullable=False),
        sa.Column("to_plan_id", sa.SmallInteger(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("razorpay_order_id", sa.Text(), nullable=True),
        sa.Column("razorpay_payment_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
        sa.ForeignKeyConstraint(["from_plan_id"], ["plans.id"]),
        sa.ForeignKeyConstraint(["to_plan_id"], ["plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("razorpay_order_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("subscription_upgrades")
