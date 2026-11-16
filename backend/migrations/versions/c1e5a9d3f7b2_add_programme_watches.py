"""Add user watches for recurring programme windows.

Revision ID: c1e5a9d3f7b2
Revises: b8d1f3a5c7e9

The foreign keys briefly lock users/programmes. Bound each attempt's lock
wait and retry inside a savepoint, following the preceding migration.
"""

import time
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision = "c1e5a9d3f7b2"
down_revision = "b8d1f3a5c7e9"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "3s"
ATTEMPTS = 120
PAUSE_SECONDS = 2.0
LOCK_NOT_AVAILABLE = "55P03"


def _with_lock_retry(change: Callable[[], None]) -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                change()
            return
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
            print(
                f"programme watch tables are busy; attempt {attempt}/{ATTEMPTS}, "
                f"retrying in {PAUSE_SECONDS:.0f}s",
                flush=True,
            )
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError(
        "Could not lock the programme watch tables in about 10 minutes. Nothing was "
        "changed. Run the migration again when background workflows are idle."
    )


def _create() -> None:
    op.create_table(
        "programme_watches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("programme_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notified_signature", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["programme_id"], ["programmes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "programme_id", name="uq_programme_watches_user_programme"),
    )
    op.create_index("ix_programme_watches_programme_id", "programme_watches", ["programme_id"])


def upgrade() -> None:
    _with_lock_retry(_create)


def downgrade() -> None:
    _with_lock_retry(lambda: op.drop_table("programme_watches"))
