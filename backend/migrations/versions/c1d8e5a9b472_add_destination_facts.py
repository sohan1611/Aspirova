"""Nullable destination evidence, without a default, index or data rewrite.

Revision ID: c1d8e5a9b472
Revises: ab6c9d2e4f71
"""

import time
from collections.abc import Callable

from alembic import op
from sqlalchemy.exc import OperationalError

revision = "c1d8e5a9b472"
down_revision = "ab6c9d2e4f71"
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
            print(f"destination migration lock busy: attempt={attempt}/{ATTEMPTS}", flush=True)
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError("Destination migration lock busy after bounded retries; run again when idle")


def upgrade() -> None:
    _with_lock_retry(
        lambda: op.get_bind().exec_driver_sql(
            "ALTER TABLE opportunities ADD COLUMN destination_facts jsonb"
        )
    )


def downgrade() -> None:
    _with_lock_retry(
        lambda: op.get_bind().exec_driver_sql(
            "ALTER TABLE opportunities DROP COLUMN destination_facts"
        )
    )
