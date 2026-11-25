"""LOCAL ONLY outage drill, no .env loading and no real provider credentials.

python -m scripts.delivery_outage_drill --database-url \
  postgresql+psycopg://postgres:postgres@127.0.0.1:5432/aspirova_delivery_test

Uses an isolated, throwaway schema; drops only that schema afterwards. The
delivery migration is exercised verbatim against minimal prerequisite tables.
"""

import argparse
import importlib.util
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from core import email_client, email_outbox, models
from core.config import Settings


@contextmanager
def isolated_delivery_database(url: str):
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"} or not parsed.database:
        raise ValueError("Drill requires an explicit localhost Postgres database")
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Drill requires PostgreSQL")
    if parsed.query:
        raise ValueError("Drill URL must not contain connection overrides")
    if not (parsed.database.endswith(("_test", "_drill")) or parsed.database.startswith("test_")):
        raise ValueError("Drill database name must identify a test database")
    schema = "delivery_drill_" + uuid.uuid4().hex
    # Pin libpq to loopback even if PGHOSTADDR/PGSERVICE exist in the shell.
    args = {"hostaddr": "::1" if parsed.host == "::1" else "127.0.0.1", "connect_timeout": 3}
    admin = create_engine(url, connect_args=args, hide_parameters=True)
    engine = create_engine(url, connect_args=args, hide_parameters=True)

    @event.listens_for(engine, "connect")
    def search_path(connection, _record):
        cursor = connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}", public')
        connection.commit()
        cursor.close()

    try:
        with admin.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.begin() as connection:
            models.User.__table__.create(connection)
            models.SavedSearch.__table__.create(connection)
            connection.exec_driver_sql("CREATE TABLE opportunities (id bigint PRIMARY KEY)")
            # Create the pre-migration ledger contract, then run the actual migration.
            connection.exec_driver_sql("""CREATE TABLE notifications (
                id bigserial PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
                type text NOT NULL, opportunity_id bigint REFERENCES opportunities(id),
                channel text DEFAULT 'email', status text NOT NULL, sent_at timestamptz,
                read_at timestamptz, meta jsonb)""")
            path = (
                Path(__file__).parents[1]
                / "migrations/versions/ab6c9d2e4f71_email_delivery_outbox.py"
            )
            spec = importlib.util.spec_from_file_location("delivery_migration", path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            # schema is a generated fixed-prefix UUID identifier, never user input.
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.dispose()


class FakeResend:
    """HTTP-compatible fake: records keys and models acceptance before a lost response."""

    def __init__(self, failures: list[object] | None = None):
        self.failures = list(failures or [])
        self.accepted: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, *, headers: dict, json: dict, timeout: int) -> httpx.Response:
        assert url == "https://api.resend.com/emails"
        assert headers["Authorization"] == "Bearer fake-outage-drill-key"
        key = headers["Idempotency-Key"]
        self.calls.append((key, json))
        failure = self.failures.pop(0) if self.failures else None
        if isinstance(failure, BaseException):
            raise failure
        if failure == "lost":
            self.accepted.setdefault(key, uuid.uuid4().hex)
            raise httpx.ReadTimeout("Fake response lost after acceptance")
        if isinstance(failure, int):
            return httpx.Response(
                failure,
                headers={"Retry-After": "120"} if failure == 429 else {},
                json={
                    "name": "validation_error" if failure == 422 else "rate_limit_exceeded",
                    "message": "Do not publish this: private@example.test re_fake-secret",
                },
            )
        self.accepted.setdefault(key, uuid.uuid4().hex)
        return httpx.Response(200, json={"id": self.accepted[key]})


def fake_settings() -> Settings:
    return Settings(
        _env_file=None,
        resend_api_key="fake-outage-drill-key",
        resend_from_email="drill@example.test",
        email_daily_budget=85,
        email_digest_reserve=10,
    )


def run_drill(engine: Engine) -> list[dict]:
    settings = fake_settings()
    now = datetime(2035, 1, 2, 12, tzinfo=timezone.utc)
    fake = FakeResend([503] * 20)
    results = []
    with (
        patch("core.email_outbox.get_settings", return_value=settings),
        patch("core.email_client.get_settings", return_value=settings),
        patch("core.email_client.httpx.post", side_effect=fake),
    ):
        with Session(engine) as session:
            users = [models.User(email=f"drill-{i}@example.test") for i in range(20)]
            session.add_all(users)
            session.commit()
            for i, user in enumerate(users):
                email_outbox.send(
                    session,
                    email_client.send_email,
                    user.email,
                    "Digest drill",
                    "",
                    "Fake digest",
                    kind="digest",
                    identity=f"drill/{i}",
                    user_id=user.id,
                    receipts=[{}],
                    now=now,
                )
            results.append({"phase": "outage", **email_outbox.status_counts(session)})
            fake.failures = []
            for row in session.query(models.EmailOutbox).all():
                email_outbox.attempt_delivery(session, row.id, now=now + timedelta(minutes=3))
            results.append({"phase": "recovered", **email_outbox.status_counts(session)})
            sent = session.query(models.Notification).filter_by(status="sent").count()
            assert sent == len(fake.accepted) == 20
            results.append(
                {
                    "accepted": len(fake.accepted),
                    "sent_events": sent,
                    "attempts": len(fake.calls),
                    "duplicate_sent_events": sent - len(fake.accepted),
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    with isolated_delivery_database(args.database_url) as engine:
        for result in run_drill(engine):
            print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
