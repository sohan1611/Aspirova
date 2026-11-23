"""Nullable stored eligibility facts, with no default or backfill (no heap rewrite).

Revision ID: fa5b8e3c7d21
Revises: f9a4d7b2c6e1
"""

import time
from collections.abc import Callable

from alembic import op
from sqlalchemy.exc import OperationalError

revision = "fa5b8e3c7d21"
down_revision = "f9a4d7b2c6e1"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "3s"
ATTEMPTS = 5
PAUSE_SECONDS = 1.0
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
                f"opportunities table is busy; attempt {attempt}/{ATTEMPTS}, "
                f"retrying in {PAUSE_SECONDS:.0f}s",
                flush=True,
            )
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError(
        "Could not lock opportunities after bounded retries. Nothing was changed. "
        "Run the migration again when background workflows are idle."
    )


def upgrade() -> None:
    _with_lock_retry(
        lambda: op.get_bind().exec_driver_sql(
            "ALTER TABLE opportunities ADD COLUMN eligibility_facts jsonb"
        )
    )


def downgrade() -> None:
    _with_lock_retry(
        lambda: op.get_bind().exec_driver_sql(
            "ALTER TABLE opportunities DROP COLUMN eligibility_facts"
        )
    )
