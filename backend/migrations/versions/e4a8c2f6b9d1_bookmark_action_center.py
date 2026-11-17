"""Optional student notes and status dates for the action center.

Revision ID: e4a8c2f6b9d1
Revises: d2f6a8c4e9b1
"""

import time
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision = "e4a8c2f6b9d1"
down_revision = "d2f6a8c4e9b1"
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
                f"bookmarks table is busy; attempt {attempt}/{ATTEMPTS}, "
                f"retrying in {PAUSE_SECONDS:.0f}s",
                flush=True,
            )
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError(
        "Could not lock the bookmarks table in about 10 minutes. Nothing was "
        "changed. Run the migration again when background workflows are idle."
    )


def _create() -> None:
    # Nullable, without defaults or backfill: existing application stages stay intact.
    op.add_column("bookmarks", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("bookmarks", sa.Column("status_date", sa.Date(), nullable=True))
    op.add_column(
        "bookmarks", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )


def upgrade() -> None:
    _with_lock_retry(_create)


def _drop() -> None:
    for name in ("status_changed_at", "status_date", "note"):
        op.drop_column("bookmarks", name)


def downgrade() -> None:
    _with_lock_retry(_drop)
