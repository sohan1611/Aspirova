"""Public report receipts and measurable founder triage.

Revision ID: d2f6a8c4e9b1
Revises: c3f7a1e5b9d2
"""

import secrets
import time
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError

revision = "d2f6a8c4e9b1"
down_revision = "c3f7a1e5b9d2"
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
                f"bug_reports table is busy; attempt {attempt}/{ATTEMPTS}, "
                f"retrying in {PAUSE_SECONDS:.0f}s",
                flush=True,
            )
            time.sleep(PAUSE_SECONDS)
    raise RuntimeError(
        "Could not lock the bug_reports table in about 10 minutes. Nothing was "
        "changed. Run the migration again when background workflows are idle."
    )


def _create() -> None:
    op.add_column("bug_reports", sa.Column("reference", sa.Text(), nullable=True))
    for name in ("triaged_at", "resolved_at"):
        op.add_column("bug_reports", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for name in ("resolution", "resolution_note"):
        op.add_column("bug_reports", sa.Column(name, sa.Text(), nullable=True))
    op.add_column("bug_reports", sa.Column("correction", JSONB(), nullable=True))
    # The table lock covers the backfill. Keep receipts opaque for legacy rows too.
    bind = op.get_bind()
    used: set[str] = set()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for report_id in bind.execute(sa.text("SELECT id FROM bug_reports ORDER BY id")).scalars():
        while True:
            reference = "R-" + "".join(secrets.choice(alphabet) for _ in range(6))
            if reference not in used:
                used.add(reference)
                break
        bind.execute(
            sa.text("UPDATE bug_reports SET reference = :reference WHERE id = :id"),
            {"reference": reference, "id": report_id},
        )
    # The founder migrates before deploying the new API. Old intake code can
    # still insert reports during that window; the new API supplies and retries
    # its own full-alphabet receipts. gen_random_uuid already exists in the schema.
    op.alter_column(
        "bug_reports",
        "reference",
        nullable=False,
        server_default=sa.text(
            "'R-' || translate(upper(substr(gen_random_uuid()::text, 1, 6)), '01', 'GH')"
        ),
    )
    op.create_unique_constraint("uq_bug_reports_reference", "bug_reports", ["reference"])


def upgrade() -> None:
    _with_lock_retry(_create)


def _drop() -> None:
    op.drop_constraint("uq_bug_reports_reference", "bug_reports", type_="unique")
    for name in (
        "correction",
        "resolution_note",
        "resolution",
        "resolved_at",
        "triaged_at",
        "reference",
    ):
        op.drop_column("bug_reports", name)


def downgrade() -> None:
    _with_lock_retry(_drop)
