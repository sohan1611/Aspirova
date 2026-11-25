"""Durable email intents, attempts, suppression and verified webhook receipts.

Revision ID: ab6c9d2e4f71
Revises: fa5b8e3c7d21
"""

import time
from collections.abc import Callable

from alembic import op
from sqlalchemy.exc import OperationalError

revision = "ab6c9d2e4f71"
down_revision = "fa5b8e3c7d21"
branch_labels = None
depends_on = None


def _with_lock_retry(change: Callable[[], None]) -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
    for attempt in range(5):
        try:
            with bind.begin_nested():
                change()
            return
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) != "55P03":
                raise
            print(f"email migration lock busy: attempt={attempt + 1}/5", flush=True)
            time.sleep(1)
    raise RuntimeError("Email migration lock busy after bounded retries; run again when idle")


CREATE = (
    """CREATE TABLE email_outbox (
        id bigserial PRIMARY KEY, user_id uuid REFERENCES users(id),
        recipient text NOT NULL, kind text NOT NULL, dedupe_key text NOT NULL UNIQUE,
        payload jsonb NOT NULL, effects jsonb NOT NULL, status text NOT NULL,
        attempts integer NOT NULL, next_attempt_at timestamptz NOT NULL,
        lease_until timestamptz, lease_token text, uncertain_since timestamptz,
        last_code integer, last_error text, retryable boolean NOT NULL,
        provider_id text UNIQUE, delivery_status text,
        created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, sent_at timestamptz,
        CONSTRAINT ck_email_outbox_status CHECK
        (status IN ('queued','sending','sent','failed','dead','suppressed'))
    )""",
    "CREATE INDEX ix_email_outbox_due ON email_outbox(status, next_attempt_at)",
    "CREATE INDEX ix_email_outbox_created ON email_outbox(created_at)",
    "CREATE INDEX ix_email_outbox_user_id ON email_outbox(user_id)",
    """CREATE TABLE email_attempts (
        outbox_id bigint NOT NULL REFERENCES email_outbox(id) ON DELETE CASCADE,
        number integer NOT NULL, started_at timestamptz NOT NULL,
        finished_at timestamptz, outcome text NOT NULL, vendor_code integer, message text,
        PRIMARY KEY(outbox_id, number)
    )""",
    "CREATE INDEX ix_email_attempts_started_at ON email_attempts(started_at)",
    "CREATE TABLE email_budget_days (day date PRIMARY KEY, used integer NOT NULL)",
    """CREATE TABLE email_suppressions (
        address text PRIMARY KEY, reason text NOT NULL, created_at timestamptz NOT NULL
    )""",
    """CREATE TABLE email_webhook_events (
        event_id text PRIMARY KEY, provider_id text NOT NULL,
        event_type text NOT NULL, created_at timestamptz NOT NULL
    )""",
    "CREATE INDEX ix_email_webhook_events_provider_id ON email_webhook_events(provider_id)",
    """ALTER TABLE notifications ADD COLUMN outbox_id bigint
       REFERENCES email_outbox(id) ON DELETE CASCADE""",
    "CREATE INDEX ix_notifications_outbox_id ON notifications(outbox_id)",
)


def _create() -> None:
    for statement in CREATE:
        op.get_bind().exec_driver_sql(statement)


def _drop() -> None:
    for statement in (
        "ALTER TABLE notifications DROP COLUMN outbox_id",
        "DROP TABLE email_webhook_events",
        "DROP TABLE email_suppressions",
        "DROP TABLE email_budget_days",
        "DROP TABLE email_attempts",
        "DROP TABLE email_outbox",
    ):
        op.get_bind().exec_driver_sql(statement)


def upgrade() -> None:
    _with_lock_retry(_create)


def downgrade() -> None:
    _with_lock_retry(_drop)
