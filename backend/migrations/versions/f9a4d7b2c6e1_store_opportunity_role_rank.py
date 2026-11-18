"""Store student role rank on writes; deliberately do not backfill here.

Revision ID: f9a4d7b2c6e1
Revises: e4a8c2f6b9d1

The nullable column has no default, so adding it does not rewrite the heap.
Existing rows use the read fallback until the founder runs backfill_role_rank.
Patterns below were generated once from the current classifier constants; this
revision never imports application code. A drift test checks the frozen body.
"""

import time
from collections.abc import Callable

from alembic import op
from sqlalchemy.exc import OperationalError

revision = "f9a4d7b2c6e1"
down_revision = "e4a8c2f6b9d1"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "3s"
ATTEMPTS = 120
PAUSE_SECONDS = 2.0
LOCK_NOT_AVAILABLE = "55P03"

ROLE_RANK_BODY_SQL = """SELECT (CASE WHEN (coalesce(title, '') ~* '(?:(?:^|[^a-z])(intern(?:s|ship|ships)?|co-?op|working[ -]+student|werkstudent)(?:[^a-z]|$))|(?:(?:^|[^a-z])(apprentice(?:s|ship|ships)?)(?:[^a-z]|$))|(?:(?:^|[^a-z])(new[ -]+(?:grads?|graduates?|college[ -]+grad(?:uate)?s?)|(?:recent|university)[ -]+grad(?:uate)?s?|graduate(?:s|[ -]+program(?:me)?s?|[ -]+schemes?)?|trainees?|freshers?|entry[ -]+level|campus)(?:[^a-z]|$))') THEN CASE WHEN (coalesce(title, '') ~* '(?:(?:^|[^a-z])(intern(?:s|ship|ships)?|co-?op|working[ -]+student|werkstudent)(?:[^a-z]|$))|(?:(?:^|[^a-z])(apprentice(?:s|ship|ships)?)(?:[^a-z]|$))') THEN 0 ELSE 1 END WHEN (category = 'internship') THEN 0 WHEN (meta['eligible_experienced_only'] = CAST('true' AS JSONB)) THEN 2 WHEN (coalesce(title, '') ~* '(?:^|[^a-z])(senior|sr|staff|principal|director|vp|vice president|president|chief|cto|ceo|coo|cfo|cxo|head of|distinguished)(?:[^a-z]|$)') THEN CASE WHEN (regexp_replace(coalesce(title, ''), '(?:^|[^a-z])(intern|interns|internship|internships|trainee|trainees|apprentice|apprentices|apprenticeship|new grad|new grads|new graduate|new graduates|graduate|graduates|campus|fresher|freshers|entry level|entry-level|co-op|coop|working student|werkstudent|technical staff|staff accountant|staff auditor|staff writer|staff nurse)(?:[^a-z]|$)', ' ', 'gi') ~* '(?:^|[^a-z])(senior|sr|staff|principal|director|vp|vice president|president|chief|cto|ceo|coo|cfo|cxo|head of|distinguished)(?:[^a-z]|$)') THEN 2 ELSE 1 END ELSE 1 END)::smallint"""


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
        "Could not lock opportunities in about 10 minutes. Nothing was changed. "
        "Run the migration again when background workflows are idle."
    )


def _create() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "CREATE OR REPLACE FUNCTION opportunity_role_rank(title text, category text, meta jsonb) "
        "RETURNS smallint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $role_rank$\n"
        + ROLE_RANK_BODY_SQL
        + "\n$role_rank$"
    )
    bind.exec_driver_sql("ALTER TABLE opportunities ADD COLUMN role_rank smallint")
    bind.exec_driver_sql("""CREATE FUNCTION set_opportunity_role_rank() RETURNS trigger
        LANGUAGE plpgsql AS $trigger$
        BEGIN
            NEW.role_rank := opportunity_role_rank(NEW.title, NEW.category, NEW.meta);
            RETURN NEW;
        END;
        $trigger$""")
    bind.exec_driver_sql("""CREATE TRIGGER opportunities_role_rank
        BEFORE INSERT OR UPDATE OF title, category, meta ON opportunities
        FOR EACH ROW EXECUTE FUNCTION set_opportunity_role_rank()""")


def _drop() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TRIGGER opportunities_role_rank ON opportunities")
    bind.exec_driver_sql("ALTER TABLE opportunities DROP COLUMN role_rank")
    bind.exec_driver_sql("DROP FUNCTION set_opportunity_role_rank()")
    bind.exec_driver_sql("DROP FUNCTION opportunity_role_rank(text, text, jsonb)")


def upgrade() -> None:
    _with_lock_retry(_create)


def downgrade() -> None:
    _with_lock_retry(_drop)
