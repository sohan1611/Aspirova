"""Action-center migration and bounded lock retries on disposable Postgres."""

import importlib.util
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


@pytest.fixture
def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/e4a8c2f6b9d1_bookmark_action_center.py"
    )
    spec = importlib.util.spec_from_file_location("bookmark_action_center_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_head_and_lock_retry(migration, monkeypatch):
    assert migration.revision == "e4a8c2f6b9d1"
    assert migration.down_revision == "d2f6a8c4e9b1"
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


def test_migration_retry_is_bounded_and_other_errors_fail(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    monkeypatch.setattr(migration, "ATTEMPTS", 2)
    monkeypatch.setattr(migration.time, "sleep", Mock())
    change = Mock(side_effect=OperationalError("ALTER", None, SimpleNamespace(sqlstate="42P07")))
    with pytest.raises(OperationalError):
        migration._with_lock_retry(change)
    change.assert_called_once_with()
    change = Mock(side_effect=OperationalError("ALTER", None, SimpleNamespace(sqlstate="55P03")))
    with pytest.raises(RuntimeError, match="Nothing was changed"):
        migration._with_lock_retry(change)
    assert change.call_count == 2


def test_postgres_upgrade_preserves_stages_without_backfill_and_downgrade(
    engine, migration, monkeypatch
):
    schema = f"bookmark_migration_{uuid.uuid4().hex}"
    stages = [
        "saved",
        "planned",
        "applied",
        "assessment",
        "interviewing",
        "offer",
        "rejected",
        "archived",
    ]
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    "CREATE TABLE bookmarks (user_id integer NOT NULL, opportunity_id integer NOT NULL, "
                    "status text NOT NULL DEFAULT 'saved', created_at timestamptz NOT NULL DEFAULT now(), "
                    "PRIMARY KEY (user_id, opportunity_id))"
                )
            )
            for index, stage in enumerate(stages):
                connection.execute(
                    text(
                        "INSERT INTO bookmarks (user_id, opportunity_id, status) VALUES (1, :id, :status)"
                    ),
                    {"id": index, "status": stage},
                )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            rows = (
                connection.execute(text("SELECT * FROM bookmarks ORDER BY opportunity_id"))
                .mappings()
                .all()
            )
            assert [row["status"] for row in rows] == stages
            assert all(
                row["note"] is None
                and row["status_date"] is None
                and row["status_changed_at"] is None
                for row in rows
            )
            columns = (
                connection.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                        "WHERE table_schema=:schema AND table_name='bookmarks'"
                    ),
                    {"schema": schema},
                )
                .mappings()
                .all()
            )
            new = {
                row["column_name"]: row
                for row in columns
                if row["column_name"] in {"note", "status_date", "status_changed_at"}
            }
            assert {name: row["data_type"] for name, row in new.items()} == {
                "note": "text",
                "status_date": "date",
                "status_changed_at": "timestamp with time zone",
            }
            assert all(
                row["is_nullable"] == "YES" and row["column_default"] is None
                for row in new.values()
            )
            stamp = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
            connection.execute(
                text(
                    "UPDATE bookmarks SET note=:note, status_date=:day, status_changed_at=:stamp WHERE opportunity_id=0"
                ),
                {"note": "Prepare", "day": date(2026, 11, 21), "stamp": stamp},
            )
            row = (
                connection.execute(text("SELECT * FROM bookmarks WHERE opportunity_id=0"))
                .mappings()
                .one()
            )
            assert (row["note"], row["status_date"], row["status_changed_at"]) == (
                "Prepare",
                date(2026, 11, 21),
                stamp,
            )
            migration.downgrade()
            columns = (
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name='bookmarks'"
                    ),
                    {"schema": schema},
                )
                .scalars()
                .all()
            )
            assert set(columns) == {"user_id", "opportunity_id", "status", "created_at"}
            assert (
                connection.execute(text("SELECT status FROM bookmarks ORDER BY opportunity_id"))
                .scalars()
                .all()
                == stages
            )
        finally:
            transaction.rollback()
