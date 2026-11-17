"""Receipt migration, bounded lock retries, and upgrade/downgrade on throwaway Postgres."""

import importlib.util
import re
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/d2f6a8c4e9b1_report_triage.py"
    spec = importlib.util.spec_from_file_location("report_triage_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_head_and_lock_retry(migration, monkeypatch):
    assert migration.revision == "d2f6a8c4e9b1"
    assert migration.down_revision == "c3f7a1e5b9d2"
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    sleep = Mock()
    monkeypatch.setattr(migration.time, "sleep", sleep)
    change = Mock(
        side_effect=[OperationalError("ALTER", None, SimpleNamespace(sqlstate="55P03")), None]
    )
    migration._with_lock_retry(change)
    bind.exec_driver_sql.assert_called_once_with("SET LOCAL lock_timeout = '3s'")
    assert bind.begin_nested.call_count == 2
    sleep.assert_called_once_with(migration.PAUSE_SECONDS)


def test_migration_does_not_retry_other_errors(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    change = Mock(side_effect=OperationalError("ALTER", None, SimpleNamespace(sqlstate="42P07")))
    with pytest.raises(OperationalError):
        migration._with_lock_retry(change)
    change.assert_called_once_with()


def test_postgres_upgrade_backfill_unique_and_downgrade(engine, migration, monkeypatch):
    schema = f"report_migration_{uuid.uuid4().hex}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    "CREATE TABLE bug_reports (id bigint PRIMARY KEY, message text NOT NULL, "
                    "status text NOT NULL DEFAULT 'open', created_at timestamptz DEFAULT now())"
                )
            )
            connection.execute(
                text("INSERT INTO bug_reports (id, message) VALUES (1, 'old'), (2, 'older')")
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            rows = (
                connection.execute(text("SELECT * FROM bug_reports ORDER BY id")).mappings().all()
            )
            assert len({r["reference"] for r in rows}) == 2
            assert all(
                re.fullmatch(r"R-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", r["reference"])
                for r in rows
            )
            assert all(
                r["status"] == "open" and r["triaged_at"] is None and r["correction"] is None
                for r in rows
            )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO bug_reports (id, message, reference) VALUES (3, 'duplicate', :ref)"
                        ),
                        {"ref": rows[0]["reference"]},
                    )
            # Old API versions omit reference until the new code deploys.
            generated = connection.scalar(
                text(
                    "INSERT INTO bug_reports (id, message) VALUES (4, 'old API') RETURNING reference"
                )
            )
            assert re.fullmatch(r"R-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", generated)
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO bug_reports (id, message, reference) VALUES (5, 'explicit null', NULL)"
                        )
                    )
            connection.execute(
                text(
                    "UPDATE bug_reports SET triaged_at=now(), resolved_at=now(), status='resolved', resolution='no_change', resolution_note='Checked', correction='[]'::jsonb WHERE id=1"
                )
            )
            migration.downgrade()
            columns = (
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name='bug_reports'"
                    ),
                    {"schema": schema},
                )
                .scalars()
                .all()
            )
            assert set(columns) == {"id", "message", "status", "created_at"}
            assert connection.scalar(text("SELECT count(*) FROM bug_reports")) == 3
        finally:
            transaction.rollback()
