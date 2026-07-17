"""Shared engine factory. Every Postgres connection in this codebase goes
through here so connection-robustness settings live in exactly one place.

Three independent mechanisms, because they bound different failure modes
(each verified by directly testing it, not assumed):

- connect_timeout: bounds the initial TCP handshake. Verified locally
  against a deliberately unreachable address: fails in exactly the
  configured time, not the OS default (which can be minutes).
- keepalives: detects a connection that goes silently dead AFTER it was
  successfully established - packets vanish without either side sending a
  TCP reset (common behind NAT/stateful firewalls on cloud CI networks).
  Without this, a query can hang forever waiting for a response that will
  never arrive, because neither endpoint knows the connection is dead.
- statement_timeout and idle_in_transaction_session_timeout: server-side
  caps on a single query and an abandoned open transaction. They are set via
  explicit `SET` commands, not the `options` connection startup parameter -
  verified that approach silently does nothing here, almost certainly because
  the Supabase pooler (PgBouncer) does not forward arbitrary startup options
  through to the backend. `SET` is a normal query over an established
  connection, which the Session pooler (chosen specifically for full session
  semantics) passes through fine.

This combination exists because connect_timeout alone was NOT sufficient:
a GitHub Actions run hung for ~4-5 minutes before its first failure twice
in a row, with connect_timeout=10 already in place - meaning the hang was
happening after a successful connection, not during the handshake. Per-
source isolation (Doc 04 sec 7) cannot hold if one stuck operation can
consume the entire time budget regardless of which layer it stalls in.

With Supabase Pro's higher session-pooler client limit, the persistent Render
server uses the correct session-mode pooler and the cap is relaxed from 5+5 to
10+10 for healthier concurrency. Pre-ping still self-heals stale connections
before checkout, while recycling prevents dead connections from lingering; the
prior free-tier-exhaustion cap is historical.

Transaction mode keeps a small SQLAlchemy QueuePool with rollback-on-return.
The transaction pooler still multiplexes those idle client connections across
server backends, while the rollback guarantees a returned connection cannot
remain idle in an open transaction.
"""

from urllib.parse import urlsplit

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from core.config import get_settings

CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_MS = 20_000
IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS = 120_000

POOL_SIZE = 10
MAX_OVERFLOW = 10
POOL_RECYCLE_SECONDS = 300

DEFAULT_CONNECT_ARGS = {
    "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    "keepalives": 1,
    "keepalives_idle": 5,
    "keepalives_interval": 5,
    "keepalives_count": 3,
}


def _resolve_transaction_mode(database_url: str, configured_mode: str) -> bool:
    if configured_mode.strip().lower() == "transaction":
        return True

    # The port IS the pooler contract. DB_POOL_MODE was a second source of
    # truth that silently drifted: GitHub Actions passes only DATABASE_URL and
    # never DB_POOL_MODE, producing session-mode settings against Supabase's
    # :6543 transaction pooler. Its connect-time statement_timeout is silently
    # dropped, letting a stuck query hang forever. Deriving mode from the port
    # makes this class of misconfiguration impossible.
    if not database_url:
        return False

    try:
        return urlsplit(database_url).port == 6543
    except (TypeError, ValueError):
        return False


def make_engine(**kwargs) -> Engine:
    settings = get_settings()
    transaction_mode = _resolve_transaction_mode(settings.database_url, settings.db_pool_mode)
    connect_args = {**DEFAULT_CONNECT_ARGS, **kwargs.pop("connect_args", {})}

    if transaction_mode:
        # Supabase's transaction-mode pooler (:6543) hands the server
        # connection back after EACH transaction, so two things the
        # session-mode setup relied on no longer hold:
        #  1) server-side prepared statements can't be reused across the
        #     rotating server backends -> disable them (psycopg
        #     prepare_threshold=None), or every query risks
        #     "prepared statement does not exist".
        #  2) connect-time settings do not survive past their own transaction
        #     -> set both server-side timeout guards with `SET LOCAL` when
        #     each transaction begins.
        connect_args.setdefault("prepare_threshold", None)

    pool_kwargs: dict = {}
    if transaction_mode:
        # Keep a bounded client QueuePool and roll every connection back before
        # reuse. PgBouncer transaction mode still multiplexes idle client
        # connections server-side, while the rollback prevents an
        # idle-in-transaction connection from lingering in the pool.
        pool_kwargs.update(
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_reset_on_return="rollback",
        )
    else:
        pool_kwargs.update(
            pool_pre_ping=True,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_recycle=POOL_RECYCLE_SECONDS,
        )

    if "poolclass" in kwargs:
        pool_kwargs.pop("pool_size", None)
        pool_kwargs.pop("max_overflow", None)
        pool_kwargs.pop("pool_recycle", None)
    pool_kwargs.update(kwargs)
    engine = create_engine(settings.database_url, connect_args=connect_args, **pool_kwargs)

    if not transaction_mode:
        # Session mode: `SET` over the established connection is honored and
        # persists for the session (verified live; the `options` startup param
        # is NOT forwarded by the session pooler - see module docstring).
        @event.listens_for(engine, "connect")
        def _set_session_timeouts(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            cursor.execute(
                "SET idle_in_transaction_session_timeout = "
                f"{IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS}"
            )
            cursor.close()

    else:
        # Transaction mode: the pooler returns the server backend to the pool
        # after every transaction, so neither a connect-time `SET` nor the
        # `options` startup param sticks (both verified ineffective against the
        # :6543 pooler - it reports the 2min default). `SET LOCAL` at the start
        # of each transaction applies both timeout guards for exactly that
        # transaction, which is the whole lifetime of one pooled server backend
        # here.
        @event.listens_for(engine, "begin")
        def _set_local_transaction_timeouts(connection) -> None:
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            connection.exec_driver_sql(
                "SET LOCAL idle_in_transaction_session_timeout = "
                f"{IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS}"
            )

    return engine
