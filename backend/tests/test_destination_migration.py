"""TRUST-01 nullable-column contract and bounded lock retry."""

import importlib.util
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import OperationalError


def migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "c1d8e5a9b472_add_destination_facts.py"
    )
    spec = importlib.util.spec_from_file_location("destination_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nullable_column_round_trip_preserves_metadata(engine, monkeypatch):
    module = migration()
    assert module.down_revision == "ab6c9d2e4f71"
    schema = "test_destination_" + uuid.uuid4().hex
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        connection.exec_driver_sql(f"SET LOCAL search_path = {schema}, public")
        connection.exec_driver_sql("CREATE TABLE opportunities (id bigint PRIMARY KEY, meta jsonb)")
        connection.exec_driver_sql("INSERT INTO opportunities VALUES (1, '{\"keep\":true}')")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        column = connection.exec_driver_sql(
            "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'opportunities' "
            "AND column_name = 'destination_facts'",
            (schema,),
        ).one()
        assert tuple(column) == ("jsonb", "YES", None)
        assert connection.exec_driver_sql(
            "SELECT meta, destination_facts FROM opportunities"
        ).one() == (
            {"keep": True},
            None,
        )
        module.downgrade()
        assert connection.exec_driver_sql("SELECT meta FROM opportunities").scalar() == {
            "keep": True
        }


@pytest.mark.parametrize("failures", [1, 5])
def test_lock_retries_are_bounded_and_use_savepoints(monkeypatch, failures):
    module = migration()
    statements, attempts = [], []
    bind = SimpleNamespace(exec_driver_sql=statements.append, begin_nested=nullcontext)
    monkeypatch.setattr(module.op, "get_bind", lambda: bind)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    def change():
        attempts.append(True)
        if len(attempts) <= failures:
            raise OperationalError("locked", {}, SimpleNamespace(sqlstate="55P03"))

    if failures == 5:
        with pytest.raises(RuntimeError, match="bounded retries"):
            module._with_lock_retry(change)
    else:
        module._with_lock_retry(change)
    assert len(attempts) == min(failures + 1, 5)
    assert statements == ["SET LOCAL lock_timeout = '3s'"]
