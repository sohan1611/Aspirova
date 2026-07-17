from types import SimpleNamespace

import pytest
from sqlalchemy.pool import NullPool

import core.db as db


def _use_local_database_url(
    monkeypatch,
    *,
    database_url: str = "postgresql+psycopg://user:password@localhost/test",
    db_pool_mode: str = "session",
) -> None:
    settings = SimpleNamespace(
        database_url=database_url,
        db_pool_mode=db_pool_mode,
    )
    monkeypatch.setattr(db, "get_settings", lambda: settings)


def _capture_create_engine_kwargs(monkeypatch) -> dict:
    captured_kwargs = {}
    original_create_engine = db.create_engine

    def capture_create_engine(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_create_engine(*args, **kwargs)

    monkeypatch.setattr(db, "create_engine", capture_create_engine)
    return captured_kwargs


def test_make_engine_uses_safe_pool_defaults(monkeypatch) -> None:
    _use_local_database_url(monkeypatch)

    engine = db.make_engine()
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool.size() == 10
        assert engine.pool._max_overflow == 10
        assert engine.pool._recycle == db.POOL_RECYCLE_SECONDS
    finally:
        engine.dispose()


def test_make_engine_allows_pool_size_override(monkeypatch) -> None:
    _use_local_database_url(monkeypatch)

    engine = db.make_engine(pool_size=1)
    try:
        assert engine.pool.size() == 1
    finally:
        engine.dispose()


def test_make_engine_does_not_force_queue_pool_options(monkeypatch) -> None:
    _use_local_database_url(monkeypatch)

    engine = db.make_engine(poolclass=NullPool)
    try:
        assert isinstance(engine.pool, NullPool)
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_make_engine_autodetects_transaction_mode_from_6543_url(monkeypatch) -> None:
    _use_local_database_url(
        monkeypatch,
        database_url="postgresql+psycopg://user:password@localhost:6543/test",
    )
    captured_kwargs = _capture_create_engine_kwargs(monkeypatch)

    engine = db.make_engine()
    try:
        assert captured_kwargs["connect_args"]["prepare_threshold"] is None
        assert captured_kwargs["pool_reset_on_return"] == "rollback"
    finally:
        engine.dispose()


def test_make_engine_keeps_session_mode_for_5432_url(monkeypatch) -> None:
    _use_local_database_url(
        monkeypatch,
        database_url="postgresql+psycopg://user:password@localhost:5432/test",
    )
    captured_kwargs = _capture_create_engine_kwargs(monkeypatch)

    engine = db.make_engine()
    try:
        assert "prepare_threshold" not in captured_kwargs["connect_args"]
        assert captured_kwargs["pool_recycle"] == db.POOL_RECYCLE_SECONDS
    finally:
        engine.dispose()


def test_make_engine_allows_transaction_mode_override_on_5432_url(monkeypatch) -> None:
    _use_local_database_url(
        monkeypatch,
        database_url="postgresql+psycopg://user:password@localhost:5432/test",
        db_pool_mode="transaction",
    )
    captured_kwargs = _capture_create_engine_kwargs(monkeypatch)

    engine = db.make_engine()
    try:
        assert captured_kwargs["connect_args"]["prepare_threshold"] is None
        assert captured_kwargs["pool_reset_on_return"] == "rollback"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "postgresql+psycopg://user:password@localhost:not-a-port/test",
    ],
)
def test_resolve_transaction_mode_falls_back_to_session_for_invalid_url(
    database_url: str,
) -> None:
    assert db._resolve_transaction_mode(database_url, "session") is False


class _ScalarResult:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _GuardConnection:
    def __init__(self, statement_timeout: str, statement_timeout_ms: str) -> None:
        self.statement_timeout = statement_timeout
        self.statement_timeout_ms = statement_timeout_ms
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> _ScalarResult:
        self.statements.append(statement)
        if statement == "SHOW statement_timeout":
            return _ScalarResult(self.statement_timeout)
        if statement == "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'":
            return _ScalarResult(self.statement_timeout_ms)
        raise AssertionError(f"Unexpected SQL: {statement}")


class _GuardTransaction:
    def __init__(self, connection: _GuardConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _GuardConnection:
        return self.connection

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        pass


class _GuardEngine:
    def __init__(self, connection: _GuardConnection) -> None:
        self.connection = connection

    def begin(self) -> _GuardTransaction:
        return _GuardTransaction(self.connection)


def test_verify_connection_guards_accepts_expected_statement_timeout() -> None:
    connection = _GuardConnection("20s", str(db.STATEMENT_TIMEOUT_MS))

    db.verify_connection_guards(_GuardEngine(connection))

    assert connection.statements == [
        "SHOW statement_timeout",
        "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'",
    ]


def test_verify_connection_guards_raises_when_statement_timeout_differs() -> None:
    connection = _GuardConnection("2min", "120000")

    with pytest.raises(
        RuntimeError,
        match=r"statement_timeout=2min, expected 20000ms",
    ):
        db.verify_connection_guards(_GuardEngine(connection))
