"""Add permanent account tombstones and retryable external cleanup.

Revision ID: c3f7a1e5b9d2
Revises: c1e5a9d3f7b2

The metadata changes briefly lock users. Bound each attempt's lock
wait and retry inside a savepoint, following the preceding migration.
"""

import time
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError

revision = "c3f7a1e5b9d2"
down_revision = "c1e5a9d3f7b2"
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
                f"users table is busy; attempt {attempt}/{ATTEMPTS}, "
                f"retrying in {PAUSE_SECONDS:.0f}s",
                flush=True,
            )
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError(
        "Could not lock the users table in about 10 minutes. Nothing was "
        "changed. Run the migration again when background workflows are idle."
    )


def _create() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("deletion_pending", JSONB(), nullable=True))
    op.alter_column("users", "email", nullable=True)
    op.alter_column("users", "created_at", nullable=True)


def upgrade() -> None:
    _with_lock_retry(_create)


def _drop() -> None:
    # Tombstones have no email. Retain that privacy guarantee on downgrade;
    # a deterministic non-deliverable placeholder satisfies the old NOT NULL.
    op.execute("UPDATE users SET email = id::text || '@deleted.invalid' WHERE email IS NULL")
    op.execute("UPDATE users SET created_at = COALESCE(deleted_at, now()) WHERE created_at IS NULL")
    op.alter_column("users", "email", nullable=False)
    op.alter_column("users", "created_at", nullable=False)
    op.drop_column("users", "deletion_pending")
    op.drop_column("users", "deleted_at")


def downgrade() -> None:
    _with_lock_retry(_drop)
