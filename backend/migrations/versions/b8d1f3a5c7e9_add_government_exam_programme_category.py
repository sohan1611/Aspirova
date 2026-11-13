"""Allow government recruitment exams in the programme registry.

Revision ID: b8d1f3a5c7e9
Revises: a7c9e2b4d6f8

Replacing a CHECK constraint needs an ACCESS EXCLUSIVE lock on `programmes`.
In production, background jobs read that table inside longer transactions:
the logo worker keeps one open while it fetches logos, and the calendar
refresh keeps one open for its whole run. The first production attempt
waited on such a lock until the 20 s statement_timeout cancelled it. A
waiting ALTER also queues every API read of the table behind it.

So each attempt waits at most LOCK_TIMEOUT for the lock, steps back, and
retries. API reads queue for a few seconds at most, and the migration lands
in the first gap between jobs. Once the lock is held, the swap itself takes
milliseconds; the scan covers about 150 rows.
"""

import time

from alembic import op
from sqlalchemy.exc import OperationalError

revision = "b8d1f3a5c7e9"
down_revision = "a7c9e2b4d6f8"
branch_labels = None
depends_on = None

OLD_CATEGORIES = (
    "research_internship",
    "fellowship",
    "government_internship",
    "open_source",
    "international_research",
    "corporate_research",
    "recurring_competition",
    "scholarship",
    "conference",
    "early_career",
)

LOCK_TIMEOUT = "3s"
ATTEMPTS = 120  # about 10 minutes with the pause below
PAUSE_SECONDS = 2.0
LOCK_NOT_AVAILABLE = "55P03"


def _replace(categories: tuple[str, ...]) -> None:
    bind = op.get_bind()
    # Scoped to this migration's transaction. Lock waits fail fast and are retried.
    bind.exec_driver_sql(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    values = ", ".join(f"'{category}'" for category in categories)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                op.drop_constraint("ck_programmes_category", "programmes", type_="check")
                op.create_check_constraint(
                    "ck_programmes_category", "programmes", f"category IN ({values})"
                )
            return
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
            print(
                f"programmes is busy (a background job holds a lock); "
                f"attempt {attempt}/{ATTEMPTS}, retrying in {PAUSE_SECONDS:.0f}s",
                flush=True,
            )
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError(
        "Could not lock the programmes table in about 10 minutes. Nothing was changed. "
        "Run the migration again when the Logos and calendar refresh workflows are idle."
    )


def upgrade() -> None:
    _replace((*OLD_CATEGORIES, "government_exam"))


def downgrade() -> None:
    # Fails transactionally until exam rows have been reclassified or removed.
    _replace(OLD_CATEGORIES)
