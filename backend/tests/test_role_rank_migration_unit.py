import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import Text, column
from sqlalchemy.dialects.postgresql import JSONB, dialect
from sqlalchemy.exc import OperationalError

from api.filters import role_rank_fallback_expression, student_rank_expression
from core import models


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """These migration unit tests never open a database cleanup connection."""
    yield


@pytest.fixture(scope="session")
def engine():
    raise AssertionError("Migration unit tests must not open a database")


@pytest.fixture
def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/f9a4d7b2c6e1_store_opportunity_role_rank.py"
    )
    spec = importlib.util.spec_from_file_location("role_rank_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_sql_matches_current_rank_patterns(migration):
    columns = SimpleNamespace(
        title=column("title", Text), category=column("category", Text), meta=column("meta", JSONB)
    )
    expression = str(
        role_rank_fallback_expression(columns).compile(
            dialect=dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert migration.ROLE_RANK_BODY_SQL == f"SELECT ({expression})::smallint"


def test_rank_is_server_generated_and_read_uses_lazy_coalesce():
    field = models.Opportunity.__table__.c.role_rank
    assert field.nullable
    assert field.default is None and field.onupdate is None
    assert field.server_default is not None and field.server_onupdate is not None
    sql = str(student_rank_expression(overrides={}).compile(dialect=dialect()))
    assert sql.startswith("coalesce(opportunities.role_rank, CASE")


def test_lock_retry_and_revision(migration, monkeypatch):
    assert migration.revision == "f9a4d7b2c6e1"
    assert migration.down_revision == "e4a8c2f6b9d1"
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    pause = Mock()
    monkeypatch.setattr(migration.time, "sleep", pause)
    change = Mock(
        side_effect=[
            OperationalError("ALTER", None, SimpleNamespace(sqlstate="55P03")),
            None,
        ]
    )
    migration._with_lock_retry(change)
    bind.exec_driver_sql.assert_called_once_with("SET LOCAL lock_timeout = '3s'")
    assert bind.begin_nested.call_count == 2
    pause.assert_called_once_with(migration.PAUSE_SECONDS)


def test_other_errors_are_not_retried(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    change = Mock(side_effect=OperationalError("ALTER", None, SimpleNamespace(sqlstate="42P07")))
    with pytest.raises(OperationalError):
        migration._with_lock_retry(change)
    change.assert_called_once_with()


def test_busy_migration_has_bounded_retries(migration, monkeypatch):
    bind = Mock()
    bind.begin_nested.side_effect = lambda: nullcontext()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    monkeypatch.setattr(migration, "ATTEMPTS", 2)
    monkeypatch.setattr(migration.time, "sleep", Mock())
    change = Mock(side_effect=OperationalError("ALTER", None, SimpleNamespace(sqlstate="55P03")))
    with pytest.raises(RuntimeError, match="Nothing was changed"):
        migration._with_lock_retry(change)
    assert change.call_count == 2


def test_upgrade_has_no_backfill_or_column_default(migration, monkeypatch):
    bind = Mock()
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: bind))
    migration._create()
    sql = [call.args[0] for call in bind.exec_driver_sql.call_args_list]
    assert "ALTER TABLE opportunities ADD COLUMN role_rank smallint" in sql
    assert not any(statement.lstrip().startswith("UPDATE ") for statement in sql)
    assert any("BEFORE INSERT OR UPDATE OF title, category, meta" in statement for statement in sql)
    assert any("IMMUTABLE PARALLEL SAFE" in statement for statement in sql)


def test_backfill_requires_explicit_database_and_positive_batch(monkeypatch, capsys):
    import sys

    from scripts.backfill_role_rank import backfill_role_rank, main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["backfill_role_rank", "--dry-run"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "Set DATABASE_URL explicitly" in capsys.readouterr().err
    with pytest.raises(ValueError, match="positive"):
        backfill_role_rank(None, batch=0)
