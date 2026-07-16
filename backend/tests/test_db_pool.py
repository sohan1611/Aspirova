from types import SimpleNamespace

from sqlalchemy.pool import NullPool

import core.db as db


def _use_local_database_url(monkeypatch) -> None:
    settings = SimpleNamespace(
        database_url="postgresql+psycopg://user:password@localhost/test",
        db_pool_mode="session",
    )
    monkeypatch.setattr(db, "get_settings", lambda: settings)


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
