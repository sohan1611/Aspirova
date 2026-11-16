"""Migration contract and bounded lock retry without running Alembic or a DB."""

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError


@pytest.fixture
def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/c3f7a1e5b9d2_add_account_deletion.py"
    )
    spec = importlib.util.spec_from_file_location("account_deletion_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chains_to_calendar_watch_and_allows_erased_email(migration, monkeypatch):
    assert migration.revision == "c3f7a1e5b9d2"
    assert migration.down_revision == "c1e5a9d3f7b2"
    operations = Mock()
    monkeypatch.setattr(migration, "op", operations)
    migration._create()
    columns = {call.args[1].name: call.args[1] for call in operations.add_column.call_args_list}
    assert columns["deleted_at"].type.timezone is True
    assert columns["deleted_at"].nullable is True
    assert columns["deletion_pending"].type.__class__.__name__ == "JSONB"
    operations.alter_column.assert_any_call("users", "email", nullable=True)
    operations.alter_column.assert_any_call("users", "created_at", nullable=True)


def test_downgrade_preserves_erasure_before_restoring_not_null(migration, monkeypatch):
    operations = Mock()
    monkeypatch.setattr(migration, "op", operations)
    migration._drop()
    assert operations.mock_calls[0].args[0] == (
        "UPDATE users SET email = id::text || '@deleted.invalid' WHERE email IS NULL"
    )
    operations.alter_column.assert_any_call("users", "email", nullable=False)
    operations.alter_column.assert_any_call("users", "created_at", nullable=False)
    assert [call.args for call in operations.drop_column.call_args_list] == [
        ("users", "deletion_pending"),
        ("users", "deleted_at"),
    ]


def test_lock_retry_uses_savepoints_and_timeout(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    sleep = Mock()
    monkeypatch.setattr(migration.time, "sleep", sleep)
    busy = OperationalError("ALTER TABLE users", None, SimpleNamespace(sqlstate="55P03"))
    change = Mock(side_effect=[busy, None])
    migration._with_lock_retry(change)
    bind.exec_driver_sql.assert_called_once_with("SET LOCAL lock_timeout = '3s'")
    assert bind.begin_nested.call_count == 2
    sleep.assert_called_once_with(migration.PAUSE_SECONDS)


def test_other_database_errors_are_not_retried(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    sleep = Mock()
    monkeypatch.setattr(migration.time, "sleep", sleep)
    change = Mock(
        side_effect=OperationalError("ALTER TABLE users", None, SimpleNamespace(sqlstate="42P07"))
    )
    with pytest.raises(OperationalError):
        migration._with_lock_retry(change)
    change.assert_called_once_with()
    sleep.assert_not_called()
