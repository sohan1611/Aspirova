"""Offline checks for the watch migration's FK contract and bounded lock retry."""

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from core.models import ProgrammeWatch


@pytest.fixture
def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/c1e5a9d3f7b2_add_programme_watches.py"
    )
    spec = importlib.util.spec_from_file_location("programme_watches_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chains_to_previous_head_and_declares_cascading_fks(migration, monkeypatch):
    assert migration.revision == "c1e5a9d3f7b2"
    assert migration.down_revision == "b8d1f3a5c7e9"
    operations = Mock()
    monkeypatch.setattr(migration, "op", operations)
    migration._create()
    table_name, *columns_and_constraints = operations.create_table.call_args.args
    assert table_name == "programme_watches"
    foreign_keys = {
        tuple(constraint.column_keys): constraint.ondelete
        for constraint in columns_and_constraints
        if constraint.__class__.__name__ == "ForeignKeyConstraint"
    }
    assert foreign_keys == {("user_id",): "CASCADE", ("programme_id",): "CASCADE"}
    assert {key.ondelete for key in ProgrammeWatch.__table__.foreign_keys} == {"CASCADE"}
    operations.create_index.assert_called_once_with(
        "ix_programme_watches_programme_id", "programme_watches", ["programme_id"]
    )


def test_lock_timeout_is_retried_with_savepoints(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    sleep = Mock()
    monkeypatch.setattr(migration.time, "sleep", sleep)
    lock_error = OperationalError(
        "CREATE TABLE programme_watches", None, SimpleNamespace(sqlstate="55P03")
    )
    change = Mock(side_effect=[lock_error, None])

    migration._with_lock_retry(change)

    bind.exec_driver_sql.assert_called_once_with("SET LOCAL lock_timeout = '3s'")
    assert bind.begin_nested.call_count == 2
    assert change.call_count == 2
    sleep.assert_called_once_with(migration.PAUSE_SECONDS)


def test_non_lock_database_errors_are_not_retried(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    sleep = Mock()
    monkeypatch.setattr(migration.time, "sleep", sleep)
    error = OperationalError(
        "CREATE TABLE programme_watches", None, SimpleNamespace(sqlstate="42P07")
    )
    change = Mock(side_effect=error)

    with pytest.raises(OperationalError) as raised:
        migration._with_lock_retry(change)

    assert raised.value is error
    change.assert_called_once_with()
    sleep.assert_not_called()
